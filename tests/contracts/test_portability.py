"""VERIFICATION-001: prevent empty, malformed, truncated, or incorrect portability evidence."""

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_portability", ROOT / "script/verification/check_portability.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@pytest.mark.parametrize("output,count", [
    ("", 1),
    ("", 0),
    ("0 0 0 0\n", 2),
    ("0 0 0 0\n0 0 0 0\n", 1),
    ("0 0 0\n", 1),
    ("0 0 0 0 0\n", 1),
    ("-1 0 0 0\n", 1),
    ("+1 0 0 0\n", 1),
    ("1.0 0 0 0\n", 1),
    ("0x1 0 0 0\n", 1),
    ("１８ 0 0 0\n", 1),
    ("18446744073709551616 0 0 0\n", 1),
    ("passed\n", 1),
    ("0 0 0 0\n\n", 1),
])
def test_portability_rejects_malformed_or_incomplete_results(output, count):
    with pytest.raises(CHECK.VerificationError):
        CHECK.parse_results(output, count)


def test_portability_preserves_unsigned_high_identity():
    assert CHECK.parse_results("9223372036854775808 0 18446744073709551615 0\n", 1) == [
        (1 << 63, 0, (1 << 64) - 1, 0)
    ]


@pytest.mark.parametrize("values", [[True], [-1], [64], [1, 1], [2, 1], [1.5], "1"])
def test_portability_rejects_ambiguous_identity_lists(values):
    with pytest.raises(CHECK.VerificationError):
        CHECK.identity_mask(values, "fixture")


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "missing-input", "missing-result", "wrong-version", "not-object"])
def test_portability_rejects_invalid_fixed_vector_suite(tmp_path, mutation):
    document = json.loads((ROOT / "tests/portability/refresh_vectors.json").read_text())
    if mutation == "empty":
        document["cases"] = []
    elif mutation == "duplicate":
        document["cases"].append(document["cases"][0])
    elif mutation == "missing-input":
        del document["cases"][0]["input"]["sources"]
    elif mutation == "missing-result":
        del document["cases"][0]["expected"]["clear"]
    elif mutation == "wrong-version":
        document["schema_version"] = True
    elif mutation == "not-object":
        document = []
    path = tmp_path / "vectors.json"
    path.write_text(json.dumps(document))
    with pytest.raises(CHECK.VerificationError):
        CHECK.load_vectors(path)


def test_portability_reports_wrong_shared_dependency_result():
    cases = CHECK.load_vectors(ROOT / "tests/portability/refresh_vectors.json")
    shared = next(case for case in cases if case["id"] == "shared-and-private")
    # The wrong implementation also clears shared identity 2 (clear mask 13 vs expected 9).
    assert CHECK.mismatches([shared], [(1, 2, 13, 1)]) == ["shared-and-private"]
    assert CHECK.mismatches([shared], [shared["expected"]]) == []


@pytest.mark.parametrize("cases,results", [([], []), ([{"id": "example", "expected": (0, 0, 0, 0)}], [])])
def test_portability_rejects_empty_or_truncated_comparisons(cases, results):
    with pytest.raises(CHECK.VerificationError):
        CHECK.mismatches(cases, results)


def test_portability_missing_driver_overwrites_stale_success_with_failure(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "summary.json").write_text('{"status":"passed"}\n')
    assert CHECK.main([
        "--cpp-driver", str(tmp_path / "missing-driver"), "--output-dir", str(output)
    ]) == 1
    summary = json.loads((output / "summary.json").read_text())
    assert summary["status"] == "failed"
    assert "missing or not executable" in summary["error"]


def test_portability_missing_compiler_is_an_error(monkeypatch):
    monkeypatch.setattr(CHECK.shutil, "which", lambda _: None)
    with pytest.raises(CHECK.VerificationError, match="required executable is unavailable"):
        CHECK.executable("rustc")
