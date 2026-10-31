"""INPUT-001 / LOCATION-001: real CLI observations with authored expectations."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((Path(__file__).parent / "fixtures/expected.json").read_text())
SPEC = importlib.util.spec_from_file_location("input_graph", ROOT / "script/verification/semantic_graph.py")
assert SPEC is not None and SPEC.loader is not None
GRAPH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAPH)


def name(serialized: str) -> str:
    return serialized.split("\tn")[-1].split("\tm")[-1].split("\ts")[0]


class Project:
    def __init__(self, root: Path, language: str, *, threads: int = 1, duplicate: bool = False):
        self.root = root
        root.mkdir()
        self.language = language
        self.source = root / ("source.py" if language == "python" else "source.cpp")
        self.project = root / "fixture.srctrlprj"
        self.database = self.project.with_suffix(".srctrldb")
        self.binary = Path(os.environ.get("SOURCETRAIL_BINARY", str(ROOT / "build/pixi/app/Sourcetrail"))).resolve()
        assert self.binary.is_file() and os.access(self.binary, os.X_OK), f"Build Sourcetrail first: {self.binary}"
        self.home = root / "home"
        settings = self.home / ".config/sourcetrail/ApplicationSettings.xml"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '<config><version>8</version><indexing>'
            f'<indexer_thread_count>{threads}</indexer_thread_count>'
            '<multi_process_indexing>0</multi_process_indexing><cxx>'
            '<has_prefilled_header_search_paths>1</has_prefilled_header_search_paths>'
            '<has_prefilled_framework_search_paths>1</has_prefilled_framework_search_paths>'
            '</cxx></indexing></config>', encoding="utf-8")
        config = ET.Element("config")
        ET.SubElement(config, "version").text = "8"
        groups = ET.SubElement(config, "source_groups")
        for index in range(2 if duplicate else 1):
            group = ET.SubElement(groups, f"source_group_input_{index}")
            ET.SubElement(group, "name").text = "Input observation fixture"
            ET.SubElement(group, "status").text = "enabled"
            if language == "python":
                ET.SubElement(group, "type").text = "Python Source Group"
                paths = ET.SubElement(group, "source_paths")
                ET.SubElement(paths, "source_path").text = self.source.name
                extensions = ET.SubElement(group, "source_extensions")
                ET.SubElement(extensions, "source_extension").text = ".py"
                interpreter = Path(os.environ.get("SOURCETRAIL_PYTHON_ENVIRONMENT",
                                   str(ROOT / ".pixi/envs/python-parser/bin/python"))).resolve()
                assert interpreter.is_file(), f"Legacy Python parser environment is required: {interpreter}"
                ET.SubElement(group, "python_environment_path").text = str(interpreter)
            else:
                ET.SubElement(group, "type").text = "C/C++ from Compilation Database"
                build = ET.SubElement(group, "build_file_path")
                ET.SubElement(build, "compilation_db_path").text = "compile_commands.json"
                (root / "compile_commands.json").write_text(json.dumps([{
                    "directory": str(root), "file": str(self.source),
                    "arguments": ["clang++", "-std=c++17", "-c", str(self.source)]}]), encoding="utf-8")
        ET.ElementTree(config).write(self.project, encoding="utf-8", xml_declaration=True)
        self.environment = dict(os.environ, HOME=str(self.home), QT_QPA_PLATFORM="offscreen",
                                SOURCETRAIL_VIA_SCRIPT="1", XDG_CONFIG_HOME=str(self.home / ".config"),
                                XDG_CACHE_HOME=str(self.home / ".cache"),
                                XDG_DATA_HOME=str(self.home / ".local/share"))
        self.runs = 0

    def text(self, symbol: str) -> str:
        if self.language == "python":
            return f"def {symbol}():\n    return 1\n"
        return f"int {symbol}() {{ return 1; }}\n"

    def index(self, *, full: bool = False, expected_exit: int = 0):
        command = [str(self.binary), "index", "--shallow"]
        if full:
            command.append("--full")
        command.append(str(self.project))
        self.runs += 1
        try:
            result = subprocess.run(command, cwd=self.root, env=self.environment,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
            (self.root / f"run-{self.runs}.log").write_text(
                f"Command: {command!r}\nTimeout: {error.timeout}\nstdout:\n{decoded(error.stdout)}"
                f"\nstderr:\n{decoded(error.stderr)}", encoding="utf-8")
            raise
        (self.root / f"run-{self.runs}.log").write_text(
            f"Command: {command!r}\nExit: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        assert result.returncode == expected_exit, result.stdout + result.stderr
        return result

    def snapshot(self):
        return GRAPH.read_snapshot(self.database, self.root)

    def assert_symbol(self, symbol: str | None):
        with sqlite3.connect(self.database) as db:
            names = {name(row[0]) for row in db.execute(
                "SELECT n.serialized_name FROM node n JOIN symbol s ON n.id=s.id WHERE n.type=4096")}
            assert (names == {symbol}) if symbol else not names
            saved = db.execute("SELECT fc.content FROM filecontent fc JOIN file f ON f.id=fc.id WHERE f.indexed=1").fetchall()
            assert saved == [(self.source.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"),)]
            assert db.execute("SELECT COUNT(*) FROM error").fetchone() == (0,)


@pytest.mark.parametrize("language", ["cxx", "python"])
@pytest.mark.parametrize("case", EXPECTED["content_cases"], ids=lambda case: case["id"])
def test_input_content_changes_and_clean_rebuild(tmp_path, language, case):
    project = Project(tmp_path / "input 日本語", language)
    project.source.write_text("" if case["change"] == "add" else project.text("before"), encoding="utf-8")
    original_time = project.source.stat().st_mtime_ns
    project.index(full=True)
    if case["change"] in {"replace", "add"}:
        project.source.write_text(project.text("after"), encoding="utf-8")
    elif case["change"] == "empty":
        project.source.write_text("", encoding="utf-8")
    elif case["change"] == "unterminated":
        project.source.write_text(project.text("before").rstrip("\n"), encoding="utf-8")
    elif case["change"] in {"missing", "null"}:
        with sqlite3.connect(project.database) as db:
            db.execute("DELETE FROM filecontent" if case["change"] == "missing" else
                       "UPDATE filecontent SET content=NULL")
    timestamp = original_time + {"same": 0, "past": -3_600_000_000_000, "future": 3_600_000_000_000}[case["timestamp"]]
    os.utime(project.source, ns=(timestamp, timestamp))
    assert project.source.stat().st_mtime_ns == timestamp
    updated = project.index()
    counts = re.findall(r"(\d+)/(\d+) source files indexed", updated.stdout)
    if case["reindexed"]:
        assert counts and counts[-1] == ("1", "1"), updated.stdout
    else:
        assert "Starting Indexing:" not in updated.stdout, updated.stdout
    project.assert_symbol(case["symbol"])
    incremental = project.snapshot()
    project.index(full=True)
    rebuilt = project.snapshot()
    assert incremental == rebuilt, GRAPH.snapshot_diff(incremental, rebuilt)


@pytest.mark.parametrize("bom", [False, True], ids=["plain", "bom"])
@pytest.mark.parametrize("ending", ["lf", "crlf", "no-final-lf", "no-final-crlf"])
def test_python_positions_select_utf8_tokens_in_stored_content(tmp_path, bom, ending):
    project = Project(tmp_path / "positions", "python")
    source = "def 日本語(値):\n    return 値\n\ndef caller():\n    return 日本語(1)\n"
    if "no-final" in ending:
        source = source.rstrip("\n")
    if "crlf" in ending:
        source = source.replace("\n", "\r\n")
    if bom:
        source = "\ufeff" + source
    project.source.write_bytes(source.encode("utf-8"))
    project.index(full=True)
    with sqlite3.connect(project.database) as db:
        saved = db.execute("SELECT content FROM filecontent").fetchone()[0]
        assert saved == source.replace("\r\n", "\n")
        rows = db.execute(
            "SELECT n.serialized_name, l.start_line, l.start_column, l.end_line, l.end_column "
            "FROM node n JOIN occurrence o ON n.id=o.element_id "
            "JOIN source_location l ON l.id=o.source_location_id WHERE n.type=4096 AND l.type=0").fetchall()
        selected = []
        for serialized, sl, sc, el, ec in rows:
            if name(serialized) == EXPECTED["positions"]["function"]:
                assert sl == el
                selected.append(saved.splitlines()[sl - 1].encode("utf-8")[sc - 1:ec].decode("utf-8"))
        assert selected and set(selected) == {"日本語"}, rows
        calls = db.execute("SELECT s.serialized_name, t.serialized_name FROM edge e "
                           "JOIN node s ON s.id=e.source_node_id JOIN node t ON t.id=e.target_node_id "
                           "WHERE e.type=8").fetchall()
        assert ("caller", "日本語") in {(name(a), name(b)) for a, b in calls}


@pytest.mark.parametrize("threads", [1, 2])
def test_repeated_python_source_is_normalized_once_per_database(tmp_path, threads):
    repeated = Project(tmp_path / "duplicates", "python", threads=threads, duplicate=True)
    repeated.source.write_text("def 日本語():\n    return 1\n", encoding="utf-8")
    repeated.index(full=True)
    duplicate_snapshot = repeated.snapshot()
    config = ET.parse(repeated.project)
    groups = config.find("source_groups")
    assert groups is not None
    groups.remove(list(groups)[-1])
    config.write(repeated.project, encoding="utf-8", xml_declaration=True)
    repeated.index(full=True)
    assert duplicate_snapshot == repeated.snapshot(), GRAPH.snapshot_diff(duplicate_snapshot, repeated.snapshot())


def test_invalid_python_output_keeps_accepted_index_and_allows_retry(tmp_path):
    project = Project(tmp_path / "invalid-output", "python")
    project.source.write_text(project.text("before"), encoding="utf-8")
    project.index(full=True)
    accepted = project.snapshot()
    project.source.write_bytes(b"def after():\n    return 1\x00\n")
    failed = project.index(expected_exit=1)
    assert "invalid" in (failed.stdout + failed.stderr).lower()
    assert project.snapshot() == accepted
    project.source.write_text(project.text("after"), encoding="utf-8")
    project.index()
    project.assert_symbol("after")
    retry = project.snapshot()
    project.index(full=True)
    assert retry == project.snapshot(), GRAPH.snapshot_diff(retry, project.snapshot())


def test_conflicting_output_owners_are_rejected_before_execution(tmp_path):
    project = Project(tmp_path / "ownership", "python")
    project.source.write_text(project.text("before"), encoding="utf-8")
    project.index(full=True)
    accepted = project.snapshot()
    settings = ET.parse(project.project)
    groups = settings.find("source_groups")
    assert groups is not None
    custom = ET.SubElement(groups, "source_group_collision")
    ET.SubElement(custom, "name").text = "Conflicting output owner"
    ET.SubElement(custom, "status").text = "enabled"
    ET.SubElement(custom, "type").text = "Custom Command Source Group"
    paths = ET.SubElement(custom, "source_paths")
    ET.SubElement(paths, "source_path").text = project.source.name
    extensions = ET.SubElement(custom, "source_extensions")
    ET.SubElement(extensions, "source_extension").text = ".py"
    ET.SubElement(custom, "custom_command").text = "/bin/true"
    ET.SubElement(custom, "run_in_parallel").text = "0"
    settings.write(project.project, encoding="utf-8", xml_declaration=True)
    result = project.index(full=True, expected_exit=1)
    assert "invalid" in (result.stdout + result.stderr).lower()
    assert project.snapshot() == accepted
    groups.remove(custom)
    settings.write(project.project, encoding="utf-8", xml_declaration=True)
    project.index(full=True)
    assert project.snapshot() == accepted
