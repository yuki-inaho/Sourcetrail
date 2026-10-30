#!/usr/bin/env python3
"""Exercise external execution through the real CLI and retain failing evidence."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from script.verification.semantic_graph import SCHEMA, SnapshotError, read_snapshot  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
INPUT_DIRECTORY = "commands 日本語 with spaces"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def has_authored_function(snapshot: dict | None, name: str) -> bool:
    # NODE_FUNCTION=4096, DEFINITION_EXPLICIT=2; authored source: int name().
    return snapshot is not None and not snapshot["errors"] and [
        ["node", 4096, ["::", [[name, "int", "()"]]]], 2,
    ] in snapshot["symbols"]


def read_index_observation(database: Path, project_root: Path) -> tuple[str, dict | None]:
    """Distinguish no accepted index from a schema-25 semantic observation.

    Project initialization creates empty tables before the first candidate exists.
    Rejecting that candidate can legitimately leave these unversioned tables. This
    exception is deliberately narrower than accepting an empty semantic graph.
    """
    if not database.exists():
        return "absent", None
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise SnapshotError("SQLite integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise SnapshotError("SQLite foreign-key check failed")
            objects = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
            tables = {name for kind, name, _, _ in objects if kind == "table"}
            non_tables = [row for row in objects if row[0] != "table"]
            expected = {**SCHEMA, "meta": ("id", "key", "value")}
            if (tables == set(expected)
                    and non_tables == [("index", "sqlite_autoindex_occurrence_1", "occurrence", None)]
                    and all(tuple(row[1] for row in db.execute(f"PRAGMA table_info({table})")) == columns
                            and db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is None
                            for table, columns in expected.items())):
                return "uninitialized-empty", None
    except sqlite3.Error as error:
        raise SnapshotError(f"Cannot inspect index database: {error}") from error
    # A valid empty schema-25 graph is still an accepted index. All other forms
    # are rejected by the unchanged semantic reader, including unversioned data.
    return "schema-25", read_snapshot(database, project_root)


class Project:
    def __init__(self, directory: Path, executable: Path, *, parallel: bool):
        self.directory = directory
        directory.mkdir(parents=True)
        self.executable = executable
        self.project = directory / "external.srctrlprj"
        self.database = self.project.with_suffix(".srctrldb")
        self.inputs = directory / INPUT_DIRECTORY
        self.inputs.mkdir()
        self.parallel = parallel
        self.config = ET.Element("config")
        ET.SubElement(self.config, "version").text = "8"
        self.groups = ET.SubElement(self.config, "source_groups")
        self.custom = None
        self.home = directory / "isolated-home"
        settings = self.home / ".config/sourcetrail/ApplicationSettings.xml"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '<config><version>8</version><indexing><indexer_thread_count>2</indexer_thread_count>'
            '<multi_process_indexing>0</multi_process_indexing><cxx>'
            '<has_prefilled_header_search_paths>1</has_prefilled_header_search_paths>'
            '<has_prefilled_framework_search_paths>1</has_prefilled_framework_search_paths>'
            '</cxx></indexing></config>\n', encoding="utf-8",
        )
        self.environment = os.environ.copy()
        self.environment.update(HOME=str(self.home), QT_QPA_PLATFORM="offscreen", SOURCETRAIL_VIA_SCRIPT="1",
                                XDG_CONFIG_HOME=str(self.home / ".config"),
                                XDG_DATA_HOME=str(self.home / ".local/share"),
                                XDG_CACHE_HOME=str(self.home / ".cache"))

    def save(self) -> None:
        ET.ElementTree(self.config).write(self.project, encoding="utf-8", xml_declaration=True)

    def commands(self, modes: dict[str, str], *, missing_executable: bool = False) -> None:
        if self.custom is None:
            self.custom = ET.SubElement(self.groups, "source_group_external")
            ET.SubElement(self.custom, "name").text = "TOY-EXTERNAL-001 process boundary"
            ET.SubElement(self.custom, "status").text = "enabled"
            ET.SubElement(self.custom, "type").text = "Custom Command Source Group"
            ET.SubElement(self.custom, "run_in_parallel").text = "1" if self.parallel else "0"
            paths = ET.SubElement(self.custom, "source_paths")
            ET.SubElement(paths, "source_path").text = str(self.inputs)
            extensions = ET.SubElement(self.custom, "source_extensions")
            ET.SubElement(extensions, "source_extension").text = ".toy"
            ET.SubElement(self.custom, "custom_command")
        self.custom.find("custom_command").text = (
            '"' + str(self.directory / "executable-that-does-not-exist") + '"'
            if missing_executable else '"%{SOURCE_FILE_PATH}"'
        )
        driver = FIXTURES / "driver.py"
        for name in modes:
            if Path(name).name != name or not name.endswith(".toy"):
                raise ValueError(f"Unsafe fixture name: {name}")
            target = self.inputs / name
            target.write_text(f"#!{sys.executable}\n" + driver.read_text(encoding="utf-8"), encoding="utf-8")
            target.chmod(0o755)
        write_json(self.inputs / "scenario.json", modes)
        self.save()

    def source(self, symbol: str) -> None:
        source = self.directory / "main.cpp"
        source.write_text(f"int {symbol}() {{ return 42; }}\n", encoding="utf-8")
        if self.groups.find("source_group_cxx") is None:
            group = ET.SubElement(self.groups, "source_group_cxx")
            ET.SubElement(group, "name").text = "Accepted index preservation seed"
            ET.SubElement(group, "status").text = "enabled"
            ET.SubElement(group, "type").text = "C/C++ from Compilation Database"
            build = ET.SubElement(group, "build_file_path")
            ET.SubElement(build, "compilation_db_path").text = "compile_commands.json"
        write_json(self.directory / "compile_commands.json", [{
            "directory": str(self.directory), "file": str(source),
            "arguments": ["clang++", "-std=c++17", "-c", str(source)],
        }])
        self.save()

    def run(self, output: Path, phase: str) -> dict:
        output.mkdir(parents=True, exist_ok=True)
        for path in self.inputs.glob("*.receipt.json"):
            path.unlink()
        command = [str(self.executable), "index", "--full", str(self.project)]
        try:
            result = subprocess.run(command, cwd=self.directory, env=self.environment, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
        except subprocess.TimeoutExpired as error:
            def decode(value: str | bytes | None) -> str:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            (output / f"{phase}.log").write_text(
                f"Command: {command!r}\nTimeout: {error.timeout}\nstdout:\n{decode(error.stdout)}"
                f"\nstderr:\n{decode(error.stderr)}", encoding="utf-8")
            raise
        log = f"Command: {command!r}\nExit: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        (output / f"{phase}.log").write_text(log, encoding="utf-8")
        counts = re.findall(r"(\d+)/(\d+) source files indexed", result.stdout)
        record = {"returncode": result.returncode, "command": command,
                  "indexed_counts": [int(v) for v in counts[-1]] if counts else None,
                  "temporary_databases": [p.name for p in self.directory.glob("*.srctrldb_tmp*")],
                  "receipts": [json.loads(p.read_text()) for p in sorted(self.inputs.glob("*.receipt.json"))],
                  "log": f"{phase}.log", "log_sha256": sha256(output / f"{phase}.log"),
                  "stderr_warning_observed": "TOY_EXTERNAL_STDERR_WARNING" in log}
        state, snapshot = read_index_observation(self.database, self.directory)
        record["database_state"] = state
        if snapshot is not None:
            write_json(output / f"{phase}.snapshot.json", snapshot)
            record.update(snapshot=f"{phase}.snapshot.json", snapshot_sha256=sha256(output / f"{phase}.snapshot.json"),
                          node_count=len(snapshot["nodes"]), indexed_files=sum(row[3] == 1 for row in snapshot["files"]))
        else:
            record.update(snapshot=None, node_count=0, indexed_files=0)
        write_json(output / f"{phase}.json", record)
        return record


def check_receipts(modes: dict[str, str], receipts: list[dict], directory: Path) -> list[str]:
    """Require exactly the selected invocations, including failures and retries."""
    errors = []
    expected = {str(directory / INPUT_DIRECTORY / name): mode for name, mode in modes.items()}
    sources = [receipt.get("source") for receipt in receipts]
    if any(not isinstance(source, str) for source in sources):
        return ["fixture receipt has no source identity"]
    if len(sources) != len(set(sources)) or set(sources) != set(expected):
        errors.append("fixture receipt sources are missing, duplicated, or unexpected")
    for receipt in receipts:
        expected_mode = expected.get(receipt["source"])
        if (receipt.get("mode") != expected_mode or receipt.get("arguments") != [] or
                receipt.get("exit_code") != (7 if expected_mode == "exit7" else 0) or
                receipt.get("cwd") != str(directory) or type(receipt.get("pid")) is not int or
                receipt["pid"] <= 0):
            errors.append("unexpected fixture invocation")
    return errors


def check_case(case: dict, observed: dict) -> list[str]:
    errors = []
    for field, expected, actual in (
        ("CLI exit", case["exit_code"], observed["returncode"]),
        ("successful count", [case["successful"], len(case["modes"])], observed["indexed_counts"]),
        ("completed fixture receipts", case["receipts"], len(observed["receipts"])),
        ("temporary databases", [], observed["temporary_databases"]),
        ("unwritten graph nodes", 0, observed["node_count"]),
        ("unwritten indexed files", 0, observed["indexed_files"]),
    ):
        if actual != expected:
            errors.append(f"{field}: expected {expected!r}, observed {actual!r}")
    if case["id"] == "stderr-zero" and not observed["stderr_warning_observed"]:
        errors.append("successful stderr output was not retained")
    allowed_states = {"schema-25"} if case["exit_code"] == 0 else {"absent", "uninitialized-empty"}
    if observed["database_state"] not in allowed_states:
        errors.append("candidate acceptance does not match the process outcome")
    errors.extend(check_receipts({} if case.get("missing_executable") else case["modes"],
                                 observed["receipts"], Path(observed["command"][-1]).parent))
    return errors


def observe_preservation(directory: Path, executable: Path, output: Path, spec: dict, *, parallel: bool) -> dict:
    project = Project(directory, executable, parallel=parallel)
    project.source(spec["seed_symbol"])
    seed = project.run(output, "seed")
    if seed["returncode"] or not seed["snapshot"]:
        raise RuntimeError(f"Could not build real C++ seed: {seed}")
    initial = json.loads((output / seed["snapshot"]).read_text())
    if not has_authored_function(initial, spec["seed_symbol"]) or seed["indexed_files"] != 1:
        raise RuntimeError("Seed did not contain its independently expected symbol and indexed file")
    project.source(spec["replacement_symbol"])
    project.commands({"failure.toy": "exit7", "success.toy": "silent-zero"})
    failed = project.run(output, "failed-update")
    failure_snapshot = json.loads((output / failed["snapshot"]).read_text()) if failed["snapshot"] else None
    project.commands({"failure.toy": "silent-zero", "success.toy": "silent-zero"})
    retry = project.run(output, "retry")
    retry_snapshot = json.loads((output / retry["snapshot"]).read_text()) if retry["snapshot"] else None
    clean = Project(directory.parent / (directory.name + " clean"), executable, parallel=parallel)
    clean.source(spec["replacement_symbol"])
    rebuilt = clean.run(output, "clean")
    clean_snapshot = json.loads((output / rebuilt["snapshot"]).read_text()) if rebuilt["snapshot"] else None
    errors = []
    checks = {
        "failure_is_nonzero": failed["returncode"] == spec["failure_exit_code"],
        "failed_command_not_counted": failed["indexed_counts"] == [spec["successful_during_failure"], spec["total_during_failure"]],
        "both_external_commands_attempted": not check_receipts(
            {"failure.toy": "exit7", "success.toy": "silent-zero"}, failed["receipts"], directory),
        "accepted_graph_preserved": failure_snapshot == initial,
        "failed_candidate_removed": not failed["temporary_databases"],
        "retry_succeeds": retry["returncode"] == spec["retry_exit_code"],
        "retry_counts_all_successes": retry["indexed_counts"] == [3, 3],
        "retry_fixtures_match_contract": not check_receipts(
            {"failure.toy": "silent-zero", "success.toy": "silent-zero"}, retry["receipts"], directory),
        "retry_candidate_removed": not retry["temporary_databases"],
        "retry_matches_clean": retry_snapshot is not None and rebuilt["returncode"] == 0 and retry_snapshot == clean_snapshot,
        "replacement_is_visible": has_authored_function(retry_snapshot, spec["replacement_symbol"]),
        "old_symbol_removed_on_retry": retry_snapshot is not None and not has_authored_function(retry_snapshot, spec["seed_symbol"]),
    }
    errors.extend(name for name, passed in checks.items() if not passed)
    return {"checks": checks, "failures": errors, "phases": {"seed": seed, "failed-update": failed, "retry": retry, "clean": rebuilt}}


def run_suite(executable: Path, output: Path, *, source_revision: str | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": 1, "toy_id": "TOY-EXTERNAL-001", "status": "failed",
               "binary_source_revision_caller_declared": source_revision, "cases": {}, "preservation": {}}
    write_json(output / "summary.json", summary)
    executable = executable.expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"Required built executable is unavailable: {executable}")
    spec = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
    summary.update(binary_sha256=sha256(executable), harness_sha256=sha256(Path(__file__)),
                   fixture_sha256={p.name: sha256(p) for p in sorted(FIXTURES.iterdir()) if p.is_file()})
    with tempfile.TemporaryDirectory(prefix="external indexer 日本語 ") as temporary:
        work = Path(temporary)
        for case in spec["cases"]:
            project = Project(work / case["id"], executable, parallel=case["parallel"])
            project.commands(case["modes"], missing_executable=case.get("missing_executable", False))
            observed = project.run(output / case["id"], "execution")
            summary["cases"][case["id"]] = {"observed": observed, "failures": check_case(case, observed)}
            write_json(output / "summary.json", summary)
        for schedule in spec["preservation"]["schedules"]:
            summary["preservation"][schedule] = observe_preservation(
                work / f"preservation-{schedule}", executable, output / f"preservation-{schedule}",
                spec["preservation"], parallel=schedule == "parallel")
            write_json(output / "summary.json", summary)
    if not any(item["failures"] for category in ("cases", "preservation") for item in summary[category].values()):
        summary["status"] = "passed"
    write_json(output / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=Path(os.environ.get("SOURCETRAIL_BINARY", ROOT / "build/pixi/app/Sourcetrail")))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary-source-revision")
    args = parser.parse_args()
    summary = run_suite(args.binary, args.output.resolve(), source_revision=args.binary_source_revision)
    print(json.dumps({"status": summary["status"], "cases": {
        category: {name: item["failures"] for name, item in summary[category].items()}
        for category in ("cases", "preservation")}, "output": str(args.output)}, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
