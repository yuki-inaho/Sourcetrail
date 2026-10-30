#!/usr/bin/env python3
"""Run checked-in toy projects through the real CLI and retain reviewable receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from script.verification.semantic_graph import (  # noqa: E402
    PROFILE, ROOT_TOKEN, read_snapshot, snapshot_diff, stable_json,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PHASES = ("initial", "no-op", "deleted", "deleted-clean", "updated", "updated-clean", "updated-no-op")
EQUALITIES = (("initial", "no-op"), ("deleted", "deleted-clean"),
              ("updated", "updated-clean"), ("updated", "updated-no-op"))


class ToyFailure(ValueError):
    """A required input, observation, or comparison is missing or different."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ToyFailure(message)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required_executable(path: Path) -> Path:
    path = path.expanduser().resolve()
    require(path.is_file() and os.access(path, os.X_OK), f"Required executable is unavailable: {path}")
    return path


def node_name(node: list) -> str:
    delimiter, parts = node[2]
    return delimiter.join(part[0] for part in parts)


def matches(node: list, selector: dict) -> bool:
    require(set(selector) <= {"name", "kind", "prefix", "postfix"} and
            {"name", "kind"} <= set(selector), f"Invalid node selector: {selector}")
    return (node[0] == "node" and node[1] == selector["kind"] and
            node_name(node) == selector["name"] and
            all(node[2][1][-1][index] == selector[key]
                for key, index in (("prefix", 1), ("postfix", 2)) if key in selector))


def check_expected(snapshot: dict, expected: dict) -> dict:
    """Independent positive and negative facts complement whole-snapshot equality."""
    require(set(expected) == {"indexed_files", "symbols", "edges", "occurrences", "forbidden_names"},
            "Unknown or missing expected-fact field")
    require(snapshot["profile"] == PROFILE and snapshot["storage_version"] == 25,
            "Unsupported snapshot profile/version")
    require(not snapshot["errors"], f"Unexpected diagnostics: {snapshot['errors']}")
    require(snapshot["nodes"] and snapshot["edges"] and snapshot["locations"], "Empty semantic result")
    indexed_files = {row[1].removeprefix(ROOT_TOKEN + "/") for row in snapshot["files"] if row[3] == 1}
    require(indexed_files == set(expected["indexed_files"]),
            f"Indexed files differ: {indexed_files!r} != {expected['indexed_files']!r}")
    require(all(row[4] == 1 for row in snapshot["files"] if row[3] == 1), "An indexed file is incomplete")
    for selector in expected["symbols"]:
        found = [node for node, _ in snapshot["symbols"] if matches(node, selector)]
        require(len(found) == 1, f"Expected exactly one symbol {selector!r}, found {len(found)}")
    for item in expected["edges"]:
        require(set(item) == {"kind", "source", "target"}, f"Invalid edge expectation: {item}")
        require(any(edge[1] == item["kind"] and matches(edge[2], item["source"]) and
                    matches(edge[3], item["target"]) for edge in snapshot["edges"]),
                f"Required directed edge is missing: {item!r}")
    for item in expected["occurrences"]:
        require(set(item) == {"symbol", "file", "range", "kind"}, f"Invalid occurrence: {item}")
        require(any(element[0] == "node" and matches(element, item["symbol"]) and
                    node_name(location[0]) == ROOT_TOKEN + "/" + item["file"] and
                    location[1:5] == item["range"] and location[5] == item["kind"]
                    for element, location in snapshot["occurrences"]),
                f"Required typed source occurrence is missing: {item!r}")
    names = {node_name(node) for node in snapshot["nodes"]}
    require(not names.intersection(expected["forbidden_names"]),
            f"Stale symbols survived: {names.intersection(expected['forbidden_names'])}")
    return {"symbols": len(expected["symbols"]), "edges": len(expected["edges"]),
            "occurrences": len(expected["occurrences"]), "forbidden_names": len(expected["forbidden_names"]),
            "indexed_files": len(indexed_files), "diagnostics": 0}


def load_spec(language: str) -> dict:
    require(language in {"cxx", "python"}, f"Unsupported toy language: {language}")
    spec = json.loads((FIXTURES / language / "expected.json").read_text(encoding="utf-8"))
    require(set(spec) == {"schema_version", "toy_id", "language", "language_profile", "snapshot_profile",
                          "adrs", "contracts", "deleted_files", "expectations"}, "Invalid toy specification fields")
    require(type(spec["schema_version"]) is int and spec["schema_version"] == 1 and spec["language"] == language and
            spec["snapshot_profile"] == PROFILE, "Unsupported toy specification")
    require(set(spec["expectations"]) == {"initial", "deleted", "updated"}, "Missing toy state")
    catalog = json.loads((ROOT / "docs/contracts/catalog.json").read_text(encoding="utf-8"))
    contract_ids = {contract["id"] for contract in catalog["contracts"]}
    require(spec["contracts"] and len(set(spec["contracts"])) == len(spec["contracts"]) and
            set(spec["contracts"]) <= contract_ids, "Unknown, missing, or duplicate toy contract")
    require(spec["adrs"] and len(set(spec["adrs"])) == len(spec["adrs"]), "Missing or duplicate toy ADR")
    for adr in spec["adrs"]:
        require(re.fullmatch(r"ADR-[0-9]{4}", adr) is not None and
                len(list((ROOT / "docs/adr").glob(f"{adr[4:]}-*.md"))) == 1,
                f"Unknown toy ADR: {adr}")
    profiles = json.loads((ROOT / "docs/contracts/language-profiles.json").read_text(encoding="utf-8"))
    require(any(profile["id"] == spec["language_profile"] and profile["status"] == "tested-fixtures" and
                profile["language"] == ("C++" if language == "cxx" else "Python")
                for profile in profiles["profiles"]), "Unknown or incompatible toy language profile")
    for relative in spec["deleted_files"]:
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts and
                (FIXTURES / language / "initial" / path).is_file() and
                not (FIXTURES / language / "updated" / path).exists(), f"Invalid deleted source: {relative}")
    return spec


class Project:
    def __init__(self, directory: Path, language: str, executable: Path, python_environment: Path | None):
        self.directory = directory
        self.language = language
        self.executable = executable
        directory.mkdir(parents=True)
        self.project_file = directory / "toy.srctrlprj"
        shutil.copyfile(FIXTURES / language / "project.srctrlprj", self.project_file)
        if language == "python":
            require(python_environment is not None, "Python parser environment is required")
            settings = ET.parse(self.project_file)
            for group in settings.getroot().find("source_groups"):
                ET.SubElement(group, "python_environment_path").text = str(python_environment)
            settings.write(self.project_file, encoding="utf-8", xml_declaration=True)
        home = directory / "isolated-home"
        configuration = home / ".config/sourcetrail/ApplicationSettings.xml"
        configuration.parent.mkdir(parents=True)
        configuration.write_text(
            '<config><version>8</version><indexing><indexer_thread_count>1</indexer_thread_count>'
            '<multi_process_indexing>0</multi_process_indexing><cxx>'
            '<has_prefilled_header_search_paths>1</has_prefilled_header_search_paths>'
            '<has_prefilled_framework_search_paths>1</has_prefilled_framework_search_paths>'
            '</cxx></indexing></config>\n', encoding="utf-8")
        self.environment = os.environ.copy()
        self.environment.update(HOME=str(home), QT_QPA_PLATFORM="offscreen", SOURCETRAIL_VIA_SCRIPT="1",
                                XDG_CONFIG_HOME=str(home / ".config"),
                                XDG_CACHE_HOME=str(home / ".cache"),
                                XDG_DATA_HOME=str(home / ".local/share"))

    def apply(self, state: str, spec: dict) -> None:
        fixture_state = "initial" if state == "deleted" else state
        fixture = FIXTURES / self.language / fixture_state
        desired = {path.relative_to(fixture): path for path in fixture.rglob("*") if path.is_file()}
        if state == "deleted":
            for relative in spec["deleted_files"]:
                desired.pop(Path(relative))
        source_dirs = ("include", "src") if self.language == "cxx" else ("first", "second")
        for source_dir in source_dirs:
            for path in (self.directory / source_dir).rglob("*"):
                if path.is_file() and path.relative_to(self.directory) not in desired:
                    path.unlink()
        for relative, source in desired.items():
            destination = self.directory / relative
            content = source.read_bytes()
            if destination.exists() and destination.read_bytes() == content:
                continue  # The deletion-only phase must not touch any surviving source.
            previous = destination.stat().st_mtime if destination.exists() else 0
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            # C++ stores mtime; the frozen external Python indexer stores wall time.
            # Advance beyond both with no sleeps, rather than masking change detection.
            timestamp = max(previous, time.time()) + 2
            os.utime(destination, (timestamp, timestamp))
        if self.language == "cxx":
            commands = [{"directory": str(self.directory), "file": str(self.directory / relative),
                         "arguments": ["clang++", "-std=c++17", "-I", str(self.directory / "include"),
                                       "-c", str(self.directory / relative)]}
                        for relative in sorted(desired) if relative.suffix == ".cpp"]
            write_json(self.directory / "compile_commands.json", commands)

    def index(self, output: Path, phase: str, *, full: bool = False) -> tuple[dict, str]:
        command = [str(self.executable), "index"] + (["--full"] if full else []) + [str(self.project_file)]
        try:
            result = subprocess.run(command, cwd=self.directory, env=self.environment, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=240)
        except subprocess.TimeoutExpired as error:
            def decode(value: str | bytes | None) -> str:
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
            log = (f"Command: {command!r}\nTimed out after {error.timeout}s\n"
                   f"stdout:\n{decode(error.stdout)}\nstderr:\n{decode(error.stderr)}")
            (output / f"{phase}.log").write_text(log, encoding="utf-8")
            raise ToyFailure(f"CLI timeout for {phase}: {log[-8000:]}") from error
        log = f"Command: {command!r}\nExit: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        (output / f"{phase}.log").write_text(log, encoding="utf-8")
        require(result.returncode == 0, f"CLI failed for {phase}: {log[-8000:]}")
        snapshot = read_snapshot(self.project_file.with_suffix(".srctrldb"), self.directory)
        write_json(output / f"{phase}.snapshot.json", snapshot)
        shutil.copyfile(self.project_file.with_suffix(".srctrldb"), output / f"{phase}.srctrldb")
        return snapshot, result.stdout


def compare_baseline(result: dict, output: Path, baseline_summary: Path) -> int:
    baseline = json.loads(baseline_summary.read_text(encoding="utf-8"))
    require(isinstance(baseline, dict), "Baseline summary must be an object")
    require(type(baseline.get("schema_version")) is int and baseline["schema_version"] == 1 and
            baseline.get("snapshot_profile") == PROFILE and
            baseline.get("status") == "passed", "Unsupported or unsuccessful baseline")
    languages = baseline.get("languages")
    require(isinstance(languages, dict), "Baseline languages must be an object")
    previous = languages.get(result["language"])
    require(isinstance(previous, dict), f"Baseline language {result['language']} must be an object")
    require(previous.get("language") == result["language"] and previous.get("toy_id") == result["toy_id"],
            "Baseline toy identity differs")
    require(previous.get("fixture_sha256") == result["fixture_sha256"], "Toy inputs or expected facts changed")
    phases = previous.get("phases")
    require(isinstance(phases, dict), "Baseline phases must be an object")
    require(set(phases) == set(PHASES), "Baseline phases are missing or unexpected")
    require(previous.get("language_profile") == result["language_profile"], "Language profiles differ")
    require(previous.get("failures") == [] and previous.get("equalities") ==
            [{"before": before, "after": after, "equal": True} for before, after in EQUALITIES],
            "Baseline contains failed or missing within-run comparisons")
    for phase in PHASES:
        record = phases[phase]
        require(isinstance(record, dict), f"Baseline phase {phase} must be an object")
        require(isinstance(record.get("checked_facts"), dict) and
                isinstance(record.get("snapshot"), str) and isinstance(record.get("snapshot_sha256"), str),
                f"Incomplete baseline phase: {phase}")
        path = baseline_summary.parent / record["snapshot"]
        require(path.resolve().is_relative_to(baseline_summary.parent.resolve()), "Baseline path escapes its directory")
        require(sha256(path) == record["snapshot_sha256"], f"Baseline snapshot checksum changed: {phase}")
        before = json.loads(path.read_text(encoding="utf-8"))
        after = json.loads((output / result["phases"][phase]["snapshot"]).read_text(encoding="utf-8"))
        require(before == after, f"Baseline differs for {result['language']}/{phase}:\n{snapshot_diff(before, after)}")
    return len(PHASES)


def run_language(language: str, output: Path, executable: Path, python_environment: Path | None,
                 baseline: Path | None = None, *, record_failures: bool = False) -> dict:
    spec = load_spec(language)
    language_output = output / language
    language_output.mkdir(parents=True, exist_ok=True)
    result = {"toy_id": spec["toy_id"], "language": language, "language_profile": spec["language_profile"],
              "fixture_sha256": {path.relative_to(FIXTURES / language).as_posix(): sha256(path)
                                 for path in sorted((FIXTURES / language).rglob("*")) if path.is_file()},
              "phases": {}, "equalities": [], "baseline_equalities": 0, "failures": []}
    snapshots = {}

    def failure(message: str) -> None:
        result["failures"].append(message)
        if not record_failures:
            raise ToyFailure(message)

    def observe(project: Project, phase: str, state: str, full: bool = False) -> None:
        snapshot, stdout = project.index(language_output, phase, full=full)
        checked = None
        try:
            checked = check_expected(snapshot, spec["expectations"][state])
            if language == "python" and phase == "deleted":
                require("Starting Indexing: 3 source files" in stdout,
                        "Later Python group deletion did not rebuild all three surviving sources")
        except ToyFailure as error:
            failure(f"{phase}: {error}")
        snapshots[phase] = snapshot
        path = language_output / f"{phase}.snapshot.json"
        result["phases"][phase] = {"state": state, "checked_facts": checked,
                                   "snapshot": path.relative_to(output).as_posix(),
                                   "snapshot_sha256": sha256(path),
                                   "counts": {key: len(value) for key, value in snapshot.items() if isinstance(value, list)}}

    def equal(before: str, after: str) -> None:
        identical = snapshots[before] == snapshots[after]
        result["equalities"].append({"before": before, "after": after, "equal": identical})
        if not identical:
            difference = snapshot_diff(snapshots[before], snapshots[after])
            (language_output / f"{before}--{after}.diff").write_text(difference, encoding="utf-8")
            failure(f"{before}/{after} differ:\n{difference}")

    with tempfile.TemporaryDirectory(prefix="sourcetrail-toy-") as temporary:
        workspace = Path(temporary)
        project = Project(workspace / "incremental 日本語 with spaces", language, executable, python_environment)
        project.apply("initial", spec)
        observe(project, "initial", "initial", True)
        observe(project, "no-op", "initial")
        equal("initial", "no-op")
        project.apply("deleted", spec)
        observe(project, "deleted", "deleted")
        clean = Project(workspace / "deleted clean 日本語 with spaces", language, executable, python_environment)
        clean.apply("deleted", spec)
        observe(clean, "deleted-clean", "deleted", True)
        equal("deleted", "deleted-clean")
        project.apply("updated", spec)
        observe(project, "updated", "updated")
        clean = Project(workspace / "updated clean 日本語 with spaces", language, executable, python_environment)
        clean.apply("updated", spec)
        observe(clean, "updated-clean", "updated", True)
        equal("updated", "updated-clean")
        observe(project, "updated-no-op", "updated")
        equal("updated", "updated-no-op")
    if baseline is not None:
        result["baseline_equalities"] = compare_baseline(result, output, baseline)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=("cxx", "python", "all"), default="all")
    parser.add_argument("--binary", type=Path, default=Path(os.environ.get("SOURCETRAIL_BINARY", ROOT / "build/pixi/app/Sourcetrail")))
    parser.add_argument("--python-environment", type=Path, default=Path(os.environ.get("SOURCETRAIL_PYTHON_ENVIRONMENT", ROOT / ".pixi/envs/python-parser/bin/python")))
    parser.add_argument("--baseline", type=Path, help="Compare every phase with this earlier run's summary.json")
    parser.add_argument("--record-failures", action="store_true",
                        help="Retain all phase observations after fact/equality failures; still exit nonzero")
    parser.add_argument("--binary-source-revision", help="Caller-declared source revision of the compiled binary")
    arguments = parser.parse_args(argv)
    output = arguments.output.resolve()
    if arguments.baseline and output == arguments.baseline.resolve().parent:
        print("Output must differ from the baseline directory; baseline receipts are read-only", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": 1, "snapshot_profile": PROFILE, "status": "failed", "languages": {}}
    # Replace an earlier success before hashing inputs or invoking any process.
    # Even an unexpected exception must leave a failed receipt, never stale green.
    write_json(output / "summary.json", summary)
    try:
        summary["verification_tools_sha256"] = {
            relative: sha256(ROOT / relative)
            for relative in ("tests/toy_projects/runner.py", "script/verification/semantic_graph.py")
        }
        summary["binary_source_revision"] = arguments.binary_source_revision
        summary["binary_source_revision_provenance"] = "caller-declared; not inferred from the working tree"
        write_json(output / "summary.json", summary)
        executable = required_executable(arguments.binary)
        environment = required_executable(arguments.python_environment) if arguments.language != "cxx" else None
        summary["binary_sha256"] = sha256(executable)
        summary["python_environment"] = str(environment) if environment else None
        for language in (("cxx", "python") if arguments.language == "all" else (arguments.language,)):
            summary["languages"][language] = run_language(language, output, executable, environment,
                                                          arguments.baseline, record_failures=arguments.record_failures)
        if all(not result["failures"] for result in summary["languages"].values()):
            summary["status"] = "passed"
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        summary["error"] = str(error)
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
