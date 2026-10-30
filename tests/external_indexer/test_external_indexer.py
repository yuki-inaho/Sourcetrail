"""EXECUTION-001: real process outcomes, candidate rejection, and successful retry."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3

import pytest

from harness import (FIXTURES, INPUT_DIRECTORY, ROOT, SCHEMA, SnapshotError, check_case,
                     check_receipts, read_index_observation, run_suite)


SPEC = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def observation(tmp_path_factory):
    output = Path(os.environ.get("SOURCETRAIL_EXTERNAL_OUTPUT", str(tmp_path_factory.mktemp("external-outcomes"))))
    executable = Path(os.environ.get("SOURCETRAIL_BINARY", str(ROOT / "build/pixi/app/Sourcetrail")))
    return run_suite(executable, output.resolve())


@pytest.mark.parametrize("case", SPEC["cases"], ids=lambda case: case["id"])
def test_external_process_outcome(observation, case):
    result = observation["cases"][case["id"]]
    assert result["failures"] == [], result


@pytest.mark.parametrize("schedule", SPEC["preservation"]["schedules"])
def test_failed_update_preserves_accepted_index(observation, schedule):
    result = observation["preservation"][schedule]
    assert result["failures"] == [], result
    assert all(result["checks"].values()), result


def valid_failure_observation():
    case = deepcopy(next(case for case in SPEC["cases"] if case["id"] == "nonzero-exit"))
    observed = {"returncode": 1, "indexed_counts": [0, 1], "temporary_databases": [],
                "database_state": "uninitialized-empty",
                "command": ["Sourcetrail", "index", "/project/external.srctrlprj"],
                "node_count": 0, "indexed_files": 0, "stderr_warning_observed": False,
                "receipts": [{"source": f"/project/{INPUT_DIRECTORY}/failure.toy", "cwd": "/project",
                              "mode": "exit7", "exit_code": 7, "arguments": [], "pid": 42}]}
    assert check_case(case, observed) == []
    return case, observed


@pytest.mark.parametrize("damage", ["exit-zero", "count-failure", "missing-receipt", "wrong-mode",
                                    "left-candidate", "unexpected-index", "accepted-failed-candidate"])
def test_fault_checker_rejects_false_success(damage):
    case, observed = valid_failure_observation()
    if damage == "exit-zero":
        observed["returncode"] = 0
    elif damage == "count-failure":
        observed["indexed_counts"] = [1, 1]
    elif damage == "missing-receipt":
        observed["receipts"] = []
    elif damage == "wrong-mode":
        observed["receipts"][0]["mode"] = "silent-zero"
    elif damage == "left-candidate":
        observed["temporary_databases"] = ["external.srctrldb_tmp_thread1"]
    elif damage == "unexpected-index":
        observed["indexed_files"] = 1
    elif damage == "accepted-failed-candidate":
        observed["database_state"] = "schema-25"
    assert check_case(case, observed), f"Checker accepted damage: {damage}"


@pytest.mark.parametrize("damage", ["duplicate-success", "wrong-retry-mode", "wrong-cwd",
                                    "wrong-exit", "unexpected-source"])
def test_receipt_checks_reject_incomplete_or_wrong_execution(damage):
    modes = {"failure.toy": "silent-zero", "success.toy": "silent-zero"}
    receipts = [{"source": f"/project/{INPUT_DIRECTORY}/{name}", "cwd": "/project",
                 "mode": mode, "exit_code": 0, "arguments": [], "pid": number + 1}
                for number, (name, mode) in enumerate(modes.items())]
    assert check_receipts(modes, receipts, Path("/project")) == []
    if damage == "duplicate-success":
        receipts[0] = deepcopy(receipts[1])
    elif damage == "wrong-retry-mode":
        receipts[0].update(mode="exit7", exit_code=7)
    elif damage == "wrong-cwd":
        receipts[0]["cwd"] = "/another-project"
    elif damage == "wrong-exit":
        receipts[0]["exit_code"] = 7
    elif damage == "unexpected-source":
        receipts[0]["source"] = f"/project/{INPUT_DIRECTORY}/unselected.toy"
    assert check_receipts(modes, receipts, Path("/project"))


def test_missing_binary_invalidates_an_older_success(tmp_path):
    (tmp_path / "summary.json").write_text('{"status": "passed"}\n')
    with pytest.raises(ValueError, match="Required built executable"):
        run_suite(tmp_path / "not-an-executable", tmp_path)
    result = json.loads((tmp_path / "summary.json").read_text())
    assert result["status"] == "failed"
    assert result["cases"] == {}


def empty_database(path):
    # Only an empty shape is needed to exercise the observation boundary. Real
    # application-created tables are independently covered by the CLI scenarios.
    with sqlite3.connect(path) as db:
        for table, columns in {**SCHEMA, "meta": ("id", "key", "value")}.items():
            constraint = ", PRIMARY KEY (element_id, source_location_id)" if table == "occurrence" else ""
            db.execute(f"CREATE TABLE {table} ({', '.join(columns)}{constraint})")


def test_absent_uninitialized_and_accepted_empty_indexes_are_distinct(tmp_path):
    database = tmp_path / "index.srctrldb"
    assert read_index_observation(database, tmp_path) == ("absent", None)
    empty_database(database)
    assert read_index_observation(database, tmp_path) == ("uninitialized-empty", None)
    with sqlite3.connect(database) as db:
        db.execute("INSERT INTO meta VALUES (1, 'storage_version', '25')")
    state, snapshot = read_index_observation(database, tmp_path)
    assert state == "schema-25"
    assert snapshot is not None and snapshot["nodes"] == []


@pytest.mark.parametrize("damage", ["unversioned-data", "unversioned-metadata", "unknown-version",
                                    "missing-column", "extra-table", "extra-view", "extra-index", "corrupt-file"])
def test_empty_index_exception_rejects_unmodelled_or_nonempty_databases(tmp_path, damage):
    database = tmp_path / "index.srctrldb"
    empty_database(database)
    with sqlite3.connect(database) as db:
        if damage == "unversioned-data":
            db.execute("INSERT INTO element VALUES (1)")
        elif damage == "unversioned-metadata":
            db.execute("INSERT INTO meta VALUES (1, 'project', 'unexpected')")
        elif damage == "unknown-version":
            db.execute("INSERT INTO meta VALUES (1, 'storage_version', '26')")
        elif damage == "missing-column":
            db.execute("ALTER TABLE meta DROP COLUMN value")
        elif damage == "extra-table":
            db.execute("CREATE TABLE future_data (id)")
        elif damage == "extra-view":
            db.execute("CREATE VIEW future_view AS SELECT * FROM node")
        elif damage == "extra-index":
            db.execute("CREATE INDEX future_index ON node (id)")
    if damage == "corrupt-file":
        database.write_bytes(b"not a SQLite database")
    with pytest.raises(SnapshotError):
        read_index_observation(database, tmp_path)


def test_fault_fixture_has_traceable_design_and_contracts():
    catalog = json.loads((ROOT / "docs/contracts/catalog.json").read_text())
    contracts = {entry["id"] for entry in catalog["contracts"]}
    assert SPEC["toy_id"] == "TOY-EXTERNAL-001"
    assert set(SPEC["contracts"]) <= contracts
    assert SPEC["contracts"]
    for adr in SPEC["adrs"]:
        assert len(list((ROOT / "docs/adr").glob(adr.removeprefix("ADR-") + "-*.md"))) == 1
