"""Exercise documentation gates with broken evidence, links, and provenance."""

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_docs", ROOT / "script" / "verification" / "check_docs.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def write_json(root, path, value):
    return write(root, path, json.dumps(value, ensure_ascii=False))


@pytest.fixture
def documentation(tmp_path):
    write(tmp_path, "docs/README.md", "# Index\n\n[Contract](contracts/README.md#contract)\n")
    write(tmp_path, "docs/contracts/README.md", "# Contract\n\nGRAPH-001\n")
    write(tmp_path, "src/example.cpp", "void example() {}\n")
    write(tmp_path, "tests/example.py", "def test_example(): pass\n")
    catalog = {
        "schema_version": 1,
        "contracts": [{
            "id": "GRAPH-001", "title": "Graph", "status": "enforced", "scope": "Fixture only",
            "sources": [{"path": "src/example.cpp", "symbol": "void example"}],
            "verification": [{"path": "tests/example.py", "anchor": "def test_example"}],
            "docs": ["docs/contracts/README.md"], "limitations": ["Not a semantic proof"],
        }],
    }
    write_json(tmp_path, "docs/contracts/catalog.json", catalog)
    write_json(tmp_path, "docs/contracts/language-profiles.json", {
        "schema_version": 1,
        "profiles": [{"id": "fixture-core", "requires_contracts": ["GRAPH-001"]}],
    })
    return tmp_path


def add_report(root):
    directory = "docs/reports/2026-10-30/001-example"
    write(root, f"{directory}/report.md", "# Report\n\nANN-001 GRAPH-001\n")
    write(root, f"{directory}/evidence/result.txt", "actual recorded result\n")
    report = {
        "schema_version": 1, "kind": "source", "batch_id": "001-example",
        "created_on": "2026-10-30", "report": "report.md",
        "source_revision": {
            "base_commit": "1" * 40, "mode": "working-tree",
            "note": "Base commit plus pending source changes; hash identifies the read snapshot",
        },
        "units": [{
            "id": "ANN-001", "path": "old/path/renamed.cpp", "symbol": "old_symbol",
            "sha256": "2" * 64, "excerpt": "recorded old source excerpt",
            "contracts": ["GRAPH-001"], "finding_type": "observed",
            "observation": "Observed snapshot behavior", "uncertainty": "Future behavior unknown",
            "next_action": "Compare the old and new behavior",
        }],
        "evidence": [{"path": f"{directory}/evidence/result.txt", "description": "Recorded result"}],
        "review": {"status": "pending", "reviewer": "local-agent"},
    }
    path = write_json(root, f"{directory}/manifest.json", report)
    return path, report


def test_consistent_contract_evidence_and_links_pass(documentation):
    errors, counts = CHECKER.validate(documentation)
    assert errors == []
    assert counts["contracts"] == 1
    assert counts["language_profiles"] == 1


@pytest.mark.parametrize("change,expected", [
    (lambda c: c.update(verification=[]), "needs verification evidence"),
    (lambda c: c["verification"][0].update(anchor="missing_test"), "literal anchor not found"),
    (lambda c: c["sources"][0].update(symbol="missing_function"), "literal symbol not found"),
    (lambda c: c["sources"][0].update(path="src/missing.cpp"), "missing path"),
    (lambda c: c.update(status="proven-everywhere"), "invalid status"),
    (lambda c: c["sources"][0].update(path="../../outside.cpp"), "escapes repository"),
])
def test_contracts_reject_missing_or_misleading_evidence(documentation, change, expected):
    path = documentation / "docs/contracts/catalog.json"
    catalog = json.loads(path.read_text())
    change(catalog["contracts"][0])
    path.write_text(json.dumps(catalog))
    errors, _ = CHECKER.validate(documentation)
    assert any(expected in error for error in errors)


def test_duplicate_contract_ids_are_rejected(documentation):
    path = documentation / "docs/contracts/catalog.json"
    catalog = json.loads(path.read_text())
    catalog["contracts"].append(catalog["contracts"][0])
    path.write_text(json.dumps(catalog))
    errors, _ = CHECKER.validate(documentation)
    assert any("duplicate contract ID" in error for error in errors)


@pytest.mark.parametrize("link,expected", [
    ("[missing](missing.md)", "broken local link"),
    ("[heading](contracts/README.md#missing)", "missing heading anchor"),
    ("[escape](../../outside.md)", "escapes repository"),
])
def test_broken_local_links_fail(documentation, link, expected):
    write(documentation, "docs/README.md", "# Index\n\n" + link)
    errors, _ = CHECKER.validate(documentation)
    assert any(expected in error for error in errors)


def test_code_examples_are_not_treated_as_real_links(documentation):
    write(documentation, "docs/README.md", "# Index\n\n```md\n[example](not-a-file.md)\n```\n")
    errors, _ = CHECKER.validate(documentation)
    assert errors == []


def test_unknown_reference_to_a_known_contract_family_fails(documentation):
    write(documentation, "docs/README.md", "# Index\n\nGRAPH-999\n")
    errors, _ = CHECKER.validate(documentation)
    assert any("unknown contract ID: GRAPH-999" in error for error in errors)


def test_historical_snapshot_is_not_rewritten_to_current_head(documentation):
    add_report(documentation)
    errors, counts = CHECKER.validate(documentation)
    assert errors == []  # The old path and old hash intentionally differ from today's source.
    assert counts["reports"] == 1


@pytest.mark.parametrize("wrong_hash", [False, True])
def test_committed_snapshot_is_checked_against_recorded_revision_not_current_file(documentation, wrong_hash):
    path, report = add_report(documentation)
    old_content = "int old_symbol = 1;\n"
    old_path = write(documentation, "old/path/renamed.cpp", old_content)
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "old/path/renamed.cpp"],
        ["git", "-c", "user.name=Contract fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Record annotation input"],
    ):
        subprocess.run(command, cwd=documentation, check=True, capture_output=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=documentation, text=True).strip()
    report["source_revision"].update(base_commit=base, mode="base-commit")
    report["units"][0].update(
        excerpt="int old_symbol = 1;",
        sha256="2" * 64 if wrong_hash else hashlib.sha256(old_content.encode()).hexdigest(),
    )
    old_path.unlink()  # A future checkout no longer has this path.
    path.write_text(json.dumps(report))
    errors, _ = CHECKER.validate(documentation)
    if wrong_hash:
        assert any("does not match the recorded base commit" in error for error in errors)
    else:
        assert errors == []


@pytest.mark.parametrize("change,expected", [
    (lambda r: r.update(kind="image"), "source reports only"),
    (lambda r: r["units"][0].update(sha256="not-a-hash"), "invalid recorded source SHA-256"),
    (lambda r: r["source_revision"].update(base_commit="abc"), "full 40-character commit SHA"),
    (lambda r: r["source_revision"].update(mode="current-head"), "mode must be"),
    (lambda r: r["source_revision"].update(note=""), "explain what the recorded base commit"),
    (lambda r: r["units"][0].update(contracts=["GRAPH-999"]), "unknown contract ID"),
    (lambda r: r["review"].update(status="completed"), "completed review"),
    (lambda r: r.update(units=r["units"] * 11), "1 to 10 source annotations"),
    (lambda r: r["evidence"][0].update(path="missing-evidence.txt"), "missing path"),
])
def test_reports_reject_false_provenance_and_missing_evidence(documentation, change, expected):
    path, report = add_report(documentation)
    change(report)
    path.write_text(json.dumps(report))
    errors, _ = CHECKER.validate(documentation)
    assert any(expected in error for error in errors)


@pytest.mark.parametrize("duplicate", [False, True])
def test_language_profiles_reject_unknown_contracts_and_duplicate_ids(documentation, duplicate):
    path = documentation / "docs/contracts/language-profiles.json"
    profiles = json.loads(path.read_text())
    if duplicate:
        profiles["profiles"].append(profiles["profiles"][0])
    else:
        profiles["profiles"][0]["requires_contracts"] = ["MISSING-001"]
    path.write_text(json.dumps(profiles))
    errors, _ = CHECKER.validate(documentation)
    assert any("duplicate profile ID" in error or "unknown contract ID" in error for error in errors)
