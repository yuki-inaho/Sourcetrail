"""Real project conformance plus negative controls for the authored fact oracle."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import runner
from runner import PHASES, ToyFailure, check_expected, compare_baseline, load_spec, main, matches, write_json


@pytest.fixture(scope="module")
def observations(tmp_path_factory):
    output = Path(os.environ.get("SOURCETRAIL_TOY_OUTPUT", tmp_path_factory.mktemp("toy-receipts"))).resolve()
    arguments = ["--output", str(output)]
    if os.environ.get("SOURCETRAIL_TOY_BASELINE"):
        arguments += ["--baseline", os.environ["SOURCETRAIL_TOY_BASELINE"]]
    result = main(arguments)
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert result == 0, summary.get("error", summary)
    return output, summary


@pytest.mark.parametrize("language", ["cxx", "python"])
def test_real_toy_project_phases_and_clean_rebuild_equivalence(observations, language):
    _, summary = observations
    result = summary["languages"][language]
    assert set(result["phases"]) == set(PHASES)
    assert len(result["equalities"]) == 4
    assert all(comparison["equal"] for comparison in result["equalities"])
    assert not result["failures"]
    if os.environ.get("SOURCETRAIL_TOY_BASELINE"):
        assert result["baseline_equalities"] == len(PHASES)


@pytest.mark.parametrize("mutation", [
    "missing-call", "reversed-call", "dropped-overload", "missing-member", "wrong-token-range", "stale-symbol",
])
def test_expected_facts_reject_damaged_real_observation(observations, mutation):
    output, _ = observations
    phase = "updated" if mutation == "stale-symbol" else "initial"
    snapshot = json.loads((output / "cxx" / f"{phase}.snapshot.json").read_text(encoding="utf-8"))
    expected = load_spec("cxx")["expectations"][phase]
    check_expected(snapshot, expected)
    damaged = copy.deepcopy(snapshot)
    if mutation in {"missing-call", "reversed-call", "missing-member"}:
        kind = 1 if mutation == "missing-member" else 8
        selected = next(edge for edge in damaged["edges"] if edge[1] == kind and
                        matches(edge[3], expected["symbols"][0]))
        if mutation == "reversed-call":
            selected[2], selected[3] = selected[3], selected[2]
        else:
            damaged["edges"].remove(selected)
    elif mutation == "dropped-overload":
        damaged["symbols"] = [row for row in damaged["symbols"] if not matches(row[0], expected["symbols"][1])]
    elif mutation == "wrong-token-range":
        selected = expected["occurrences"][0]
        for element, location in damaged["occurrences"]:
            if element[0] == "node" and matches(element, selected["symbol"]) and location[1:5] == selected["range"]:
                location[2] += 1
    else:
        original = json.loads((output / "cxx/initial.snapshot.json").read_text(encoding="utf-8"))
        stale = next(node for node, _ in original["symbols"]
                     if matches(node, load_spec("cxx")["expectations"]["initial"]["symbols"][0]))
        damaged["nodes"].append(stale)
    with pytest.raises(ToyFailure):
        check_expected(damaged, expected)


@pytest.mark.parametrize("damage", [
    "version", "profile", "missing-language", "missing-phase", "checksum", "failed", "failed-equality",
])
def test_baseline_comparison_rejects_unusable_receipts(observations, damage):
    output, summary = observations
    malformed = copy.deepcopy(summary)
    if damage == "version":
        malformed["schema_version"] = 2
    elif damage == "profile":
        malformed["snapshot_profile"] = "unknown"
    elif damage == "missing-language":
        del malformed["languages"]["cxx"]
    elif damage == "missing-phase":
        del malformed["languages"]["cxx"]["phases"]["updated"]
    elif damage == "checksum":
        malformed["languages"]["cxx"]["phases"]["initial"]["snapshot_sha256"] = "0" * 64
    elif damage == "failed-equality":
        malformed["languages"]["cxx"]["equalities"][0]["equal"] = False
    else:
        malformed["status"] = "failed"
    path = output / f"malformed-{damage}.json"
    write_json(path, malformed)
    with pytest.raises(ToyFailure):
        compare_baseline(summary["languages"]["cxx"], output, path)


def test_missing_executable_is_failure_with_receipt(tmp_path):
    output = tmp_path / "receipt"
    assert main(["--output", str(output), "--binary", str(tmp_path / "missing"), "--language", "cxx"]) == 1
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert "Required executable is unavailable" in summary["error"]


@pytest.mark.parametrize("damage", ["contract", "adr", "language-profile", "state"])
def test_toy_spec_rejects_traceability_drift(tmp_path, monkeypatch, damage):
    spec = load_spec("cxx")
    if damage == "contract":
        spec["contracts"].append("GRAPH-999")
    elif damage == "adr":
        spec["adrs"].append("ADR-9999")
    elif damage == "language-profile":
        spec["language_profile"] = "python-jedi017-full"
    else:
        del spec["expectations"]["deleted"]
    write_json(tmp_path / "cxx/expected.json", spec)
    monkeypatch.setattr(runner, "FIXTURES", tmp_path)
    with pytest.raises(ToyFailure):
        load_spec("cxx")


def test_output_cannot_overwrite_baseline(tmp_path):
    baseline = tmp_path / "summary.json"
    original = b'{"preserve": "this receipt"}\n'
    baseline.write_bytes(original)
    assert main(["--output", str(tmp_path), "--baseline", str(baseline)]) == 2
    assert baseline.read_bytes() == original


def test_timeout_preserves_both_process_streams(tmp_path, monkeypatch):
    project = runner.Project(tmp_path / "project", "cxx", Path(sys.executable), None)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 240, output=b"partial stdout", stderr="partial stderr")

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    with pytest.raises(ToyFailure, match="CLI timeout"):
        project.index(tmp_path, "timed-out")
    log = (tmp_path / "timed-out.log").read_text(encoding="utf-8")
    assert "partial stdout" in log and "partial stderr" in log and "Timed out" in log


@pytest.mark.parametrize("shape", ["summary", "languages", "language-entry", "phases", "phase-record"])
def test_baseline_comparison_rejects_malformed_object_shapes(tmp_path, shape):
    # These malformed metadata inputs must fail before any snapshot is opened.
    result = {"language": "cxx", "toy_id": "TOY-CXX-001", "fixture_sha256": {},
              "language_profile": "cxx-clang11-core"}
    previous = {
        **result, "failures": [],
        "equalities": [{"before": before, "after": after, "equal": True}
                       for before, after in runner.EQUALITIES],
        "phases": {phase: {"checked_facts": {}, "snapshot": "must-not-open.json",
                           "snapshot_sha256": "0" * 64} for phase in PHASES},
    }
    baseline = {"schema_version": 1, "snapshot_profile": runner.PROFILE, "status": "passed",
                "languages": {"cxx": previous}}
    if shape == "summary":
        baseline = []
    elif shape == "languages":
        baseline["languages"] = []
    elif shape == "language-entry":
        baseline["languages"]["cxx"] = []
    elif shape == "phases":
        previous["phases"] = []
    else:
        previous["phases"][PHASES[0]] = []
    path = tmp_path / "malformed-summary.json"
    write_json(path, baseline)
    with pytest.raises(ToyFailure, match="Baseline .* must be an object"):
        compare_baseline(result, tmp_path, path)


@pytest.mark.parametrize("failure", ["malformed-baseline", "unexpected-exception"])
def test_failed_rerun_invalidates_previous_success_before_work(tmp_path, monkeypatch, failure):
    output = tmp_path / "rerun"
    receipt = output / "summary.json"
    write_json(receipt, {"status": "passed", "stale": "old successful execution"})
    baseline = tmp_path / "baseline/summary.json"
    write_json(baseline, {"schema_version": 1, "snapshot_profile": runner.PROFILE,
                         "status": "passed", "languages": []})

    def fail_before_indexing(language, output, executable, environment, baseline, **kwargs):
        assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "failed"
        if failure == "malformed-baseline":
            return compare_baseline({"language": language}, output, baseline)
        raise RuntimeError("unexpected verification failure")

    monkeypatch.setattr(runner, "run_language", fail_before_indexing)
    arguments = ["--output", str(output), "--binary", sys.executable, "--language", "cxx",
                 "--baseline", str(baseline)]
    if failure == "malformed-baseline":
        assert main(arguments) == 1
    else:
        with pytest.raises(RuntimeError, match="unexpected verification failure"):
            main(arguments)
    final = json.loads(receipt.read_text(encoding="utf-8"))
    assert final["status"] == "failed" and "stale" not in final
    assert final["verification_tools_sha256"] == {
        relative: runner.sha256(runner.ROOT / relative)
        for relative in ("tests/toy_projects/runner.py", "script/verification/semantic_graph.py")
    }


def test_boolean_is_not_schema_version_one(tmp_path, monkeypatch):
    spec = load_spec("cxx")
    spec["schema_version"] = True
    write_json(tmp_path / "cxx/expected.json", spec)
    monkeypatch.setattr(runner, "FIXTURES", tmp_path)
    with pytest.raises(ToyFailure, match="Unsupported toy specification"):
        load_spec("cxx")
    baseline = tmp_path / "summary.json"
    write_json(baseline, {"schema_version": True, "snapshot_profile": runner.PROFILE,
                         "status": "passed", "languages": {}})
    with pytest.raises(ToyFailure, match="Unsupported or unsuccessful baseline"):
        compare_baseline({"language": "cxx"}, tmp_path, baseline)
