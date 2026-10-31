"""Use the real application to publish, refresh and reject modern adapter output."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import xml.etree.ElementTree as ET

import pytest

from script.indexers.cli import configure_project
from script.verification.semantic_graph import read_snapshot, snapshot_diff


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "build/modern-indexers/e2e"


def label(value: str) -> str:
    delimiter, _, rest = value.partition("\tm")
    return delimiter.join(part.partition("\ts")[0] for part in rest.split("\tn"))


class Project:
    def __init__(self, root: Path, language: str, case: str):
        self.root, self.language = root, language
        root.mkdir(parents=True)
        self.binary = Path(os.environ.get("SOURCETRAIL_BINARY", str(ROOT / "build/pixi/app/Sourcetrail"))).resolve()
        assert self.binary.is_file() and os.access(self.binary, os.X_OK), f"Build the real app first: {self.binary}"
        self.project = root / "project.srctrlprj"
        self.database = self.project.with_suffix(".srctrldb")
        # Sourcetrail installs example projects in its application home on first
        # startup. Keep that writable state outside the source tree being tested.
        self.home = root.parent / (root.name + "-home")
        settings = self.home / ".config/sourcetrail/ApplicationSettings.xml"
        settings.parent.mkdir(parents=True)
        settings.write_text('<config><version>8</version><indexing><indexer_thread_count>2</indexer_thread_count>'
                            '<multi_process_indexing>0</multi_process_indexing><cxx>'
                            '<has_prefilled_header_search_paths>1</has_prefilled_header_search_paths>'
                            '<has_prefilled_framework_search_paths>1</has_prefilled_framework_search_paths>'
                            '</cxx></indexing></config>', encoding="utf-8")
        self.environment = dict(os.environ, HOME=str(self.home), QT_QPA_PLATFORM="offscreen", SOURCETRAIL_VIA_SCRIPT="1",
                                XDG_CONFIG_HOME=str(self.home / ".config"), XDG_DATA_HOME=str(self.home / ".local/share"),
                                XDG_CACHE_HOME=str(self.home / ".cache"))
        self.evidence = OUTPUT / case
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.runs = 0

    def configure(self):
        _, self.config = configure_project(self.language, self.root, self.project)

    def run(self, *, full=False, success=True):
        arguments = [str(self.binary), "index"] + (["--full"] if full else []) + [str(self.project)]
        result = subprocess.run(arguments, cwd=self.root, env=self.environment, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=240)
        self.runs += 1
        (self.evidence / f"run-{self.runs}.log").write_text(
            f"Command: {arguments!r}\nExit: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}", encoding="utf-8")
        assert result.returncode == (0 if success else 1), result.stdout + result.stderr
        return result

    def snapshot(self):
        snapshot = read_snapshot(self.database, self.root)
        (self.evidence / f"run-{self.runs}.snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot

    def names(self):
        with sqlite3.connect(self.database) as db:
            return {label(name) for (name,) in db.execute("SELECT serialized_name FROM node JOIN symbol USING(id) WHERE definition_kind=2")}

    def assert_call(self, source, target):
        with sqlite3.connect(self.database) as db:
            calls = {(label(s), label(t)) for s, t in db.execute(
                "SELECT s.serialized_name,t.serialized_name FROM edge e JOIN node s ON s.id=e.source_node_id "
                "JOIN node t ON t.id=e.target_node_id WHERE e.type=8")}
        assert (source, target) in calls


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_real_app_refresh_delete_empty_and_clean_equivalence(tmp_path, language):
    project = Project(tmp_path / "project 日本語", language, "refresh-" + language)
    suffix = ".py" if language == "python" else ".cpp"
    source = project.root / ("example" + suffix)
    obsolete = project.root / ("obsolete" + suffix)
    source.write_text("def target():\n    return 1\ndef entry():\n    return target()\n" if language == "python" else
                      "int target(){return 1;}\nint entry(){return target();}\n", encoding="utf-8")
    obsolete.write_text("def obsolete():\n    return 0\n" if language == "python" else "int obsolete(){return 0;}\n", encoding="utf-8")
    if language == "cpp":
        (project.root / "compile_commands.json").write_text(json.dumps([
            {"directory": str(project.root), "file": str(path), "arguments": ["clang++", "-std=c++23", "-c", str(path)]}
            for path in (source, obsolete)]))
    project.configure()
    project.run(full=True)
    before = project.snapshot()
    prefix = "example." if language == "python" else ""
    project.assert_call(prefix + "entry", prefix + "target")
    noop = project.run()
    assert "Starting Indexing:" not in noop.stdout
    assert project.snapshot() == before
    previous_time = source.stat().st_mtime_ns
    source.write_text(source.read_text().replace("target", "replacement"), encoding="utf-8")
    os.utime(source, ns=(previous_time, previous_time))
    obsolete.unlink()
    if language == "cpp":
        (project.root / "compile_commands.json").write_text(json.dumps([
            {"directory": str(project.root), "file": str(source), "arguments": ["clang++", "-std=c++23", "-c", str(source)]}]))
    project.run()
    names = project.names()
    assert prefix + "replacement" in names
    assert prefix + "target" not in names
    assert not any("obsolete" in name for name in names)
    project.assert_call(prefix + "entry", prefix + "replacement")
    changed = project.snapshot()
    project.run(full=True)
    assert project.snapshot() == changed, snapshot_diff(changed, project.snapshot())
    source.unlink()
    if language == "cpp":
        (project.root / "compile_commands.json").write_text("[]\n")
    project.run()
    assert not project.names()
    empty = project.snapshot()
    project.run(full=True)
    assert project.snapshot() == empty


def test_real_app_rust_workspace_refresh_delete_and_clean_equivalence(tmp_path):
    project = Project(tmp_path / "rust project", "rust", "refresh-rust")
    fixture = Path(__file__).parent / "fixtures/rust"
    shutil.copytree(fixture, project.root, dirs_exist_ok=True)
    project.configure()
    project.run(full=True)
    assert "shapes::Square" in project.names()
    project.assert_call("shape_app::run", "shapes::impl Measure for Square::measure")
    before = project.snapshot()
    assert "Starting Indexing:" not in project.run().stdout
    assert project.snapshot() == before
    (project.root / "shapes/src/operations.rs").unlink()
    (project.root / "shapes/src/lib.rs").write_text("pub fn replacement() -> i32 { 13 }\n", encoding="utf-8")
    (project.root / "app/src/main.rs").write_text("fn main() { let _value = shapes::replacement(); }\n", encoding="utf-8")
    project.run()
    assert "shapes::replacement" in project.names()
    assert not any("Square" in name or "operations" in name for name in project.names())
    changed = project.snapshot()
    project.run(full=True)
    assert project.snapshot() == changed, snapshot_diff(changed, project.snapshot())


@pytest.mark.parametrize("language", ["python", "cpp", "rust"])
def test_real_app_rejects_protocol_mismatch_preserves_index_and_retries(tmp_path, language):
    project = Project(tmp_path / "preserve", language, "failure-" + language)
    if language == "python":
        (project.root / "main.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    elif language == "cpp":
        (project.root / "main.cpp").write_text("int keep(){return 1;}\n", encoding="utf-8")
    else:
        (project.root / "Cargo.toml").write_text('[package]\nname="preserve"\nversion="0.1.0"\nedition="2024"\n', encoding="utf-8")
        (project.root / "src").mkdir()
        (project.root / "src/lib.rs").write_text("pub fn keep() -> i32 { 1 }\n", encoding="utf-8")
        subprocess.run(["cargo", "generate-lockfile", "--offline"], cwd=project.root,
                       env=project.environment, capture_output=True, check=True, timeout=30)
    project.configure()
    project.run(full=True)
    accepted = project.snapshot()
    original = project.config.read_text(encoding="utf-8")
    wrong = json.loads(original)
    wrong["protocol_version"] = 999
    project.config.write_text(json.dumps(wrong), encoding="utf-8")
    failed = project.run(success=False)
    assert "Unsupported adapter protocol" in failed.stdout + failed.stderr
    assert project.snapshot() == accepted
    project.config.write_text(original, encoding="utf-8")
    project.run(full=True)
    assert project.snapshot() == accepted


def test_real_app_modern_crlf_input_does_not_reindex_without_changes(tmp_path):
    project = Project(tmp_path / "crlf", "python", "crlf-noop")
    (project.root / "source.py").write_bytes("\ufeffdef 日本語():\r\n    return 1\r\n".encode("utf-8"))
    project.configure()
    project.run(full=True)
    accepted = project.snapshot()
    assert "Starting Indexing:" not in project.run().stdout
    assert project.snapshot() == accepted


def test_existing_python_common_capabilities_match_both_engines(tmp_path):
    project = Project(tmp_path / "common", "python", "python-common")
    (project.root / "sample.py").write_text(
        "class Parent:\n    def method(self):\n        return 1\nclass Child(Parent):\n    pass\n"
        "def target():\n    return 7\ndef caller():\n    return target()\n", encoding="utf-8")
    project.configure()
    project.run(full=True)
    modern_db = project.database.read_bytes()
    modern_names = project.names()
    project.assert_call("sample.caller", "sample.target")
    modern_tree = ET.parse(project.project)
    group = modern_tree.getroot().find("source_groups")[0]
    group.find("type").text = "Python Source Group"
    ET.SubElement(group, "python_environment_path").text = str(ROOT / ".pixi/envs/python-parser/bin/python")
    modern_tree.write(project.project, encoding="utf-8", xml_declaration=True)
    project.run(full=True)
    legacy_names = project.names()
    project.assert_call("sample.caller", "sample.target")
    expected = {"sample.Parent", "sample.Parent.method", "sample.Child", "sample.target", "sample.caller"}
    assert expected <= modern_names
    assert expected <= legacy_names
    with sqlite3.connect(project.database) as db:
        legacy_inheritance = {(label(s), label(t)) for s, t in db.execute(
            "SELECT s.serialized_name,t.serialized_name FROM edge e JOIN node s ON s.id=e.source_node_id JOIN node t ON t.id=e.target_node_id WHERE e.type=16")}
    modern_copy = tmp_path / "modern.db"
    modern_copy.write_bytes(modern_db)
    with sqlite3.connect(modern_copy) as db:
        modern_inheritance = {(label(s), label(t)) for s, t in db.execute(
            "SELECT s.serialized_name,t.serialized_name FROM edge e JOIN node s ON s.id=e.source_node_id JOIN node t ON t.id=e.target_node_id WHERE e.type=16")}
    assert ("sample.Child", "sample.Parent") in legacy_inheritance & modern_inheritance


def _legacy_group(project: Project, source: Path) -> None:
    tree = ET.parse(project.project)
    group = ET.SubElement(tree.getroot().find("source_groups"), "source_group_legacy")
    ET.SubElement(group, "type").text = "Python Source Group"
    ET.SubElement(group, "status").text = "enabled"
    paths = ET.SubElement(group, "source_paths")
    ET.SubElement(paths, "source_path").text = str(source)
    extensions = ET.SubElement(group, "source_extensions")
    ET.SubElement(extensions, "source_extension").text = ".py"
    ET.SubElement(group, "python_environment_path").text = str(ROOT / ".pixi/envs/python-parser/bin/python")
    tree.write(project.project, encoding="utf-8", xml_declaration=True)


def _indexer_threads(project: Project, threads: int) -> None:
    settings = project.home / ".config/sourcetrail/ApplicationSettings.xml"
    tree = ET.parse(settings)
    tree.find("indexing/indexer_thread_count").text = str(threads)
    tree.write(settings, encoding="utf-8", xml_declaration=True)


@pytest.mark.parametrize("threads", [1, 2])
def test_mixed_legacy_and_modern_python_keep_separate_coordinate_domains(tmp_path, threads):
    project = Project(tmp_path / "mixed", "python", f"mixed-coordinates-{threads}")
    modern = project.root / "modern"
    legacy = project.root / "legacy"
    modern.mkdir()
    legacy.mkdir()
    modern_source = modern / "new.py"
    legacy_source = legacy / "old.py"
    modern_source.write_text("\ufeffdef 新関数():\n    return 2\ndef caller():\n    return 新関数()\n", encoding="utf-8")
    legacy_source.write_text("def 旧関数():\n    return 1\n", encoding="utf-8")
    _, project.config = configure_project("python", project.root, project.project, options={"source_roots": ["modern"]})
    _legacy_group(project, legacy_source)
    _indexer_threads(project, threads)
    project.run(full=True)
    project.assert_call("new.caller", "new.新関数")
    with sqlite3.connect(project.database) as db:
        selected = {}
        for serialized, path, line, start, end, content in db.execute(
            "SELECT n.serialized_name,f.path,l.start_line,l.start_column,l.end_column,fc.content "
            "FROM node n JOIN symbol s ON s.id=n.id JOIN occurrence o ON o.element_id=n.id "
            "JOIN source_location l ON l.id=o.source_location_id JOIN file f ON f.id=l.file_node_id "
            "JOIN filecontent fc ON fc.id=f.id WHERE n.type=4096 AND l.type=0"):
            selected[label(serialized)] = (Path(path), content.splitlines()[line - 1].encode("utf-8")[start - 1:end].decode("utf-8"))
        assert selected["new.新関数"] == (modern_source, "新関数")
        assert selected["old.旧関数"] == (legacy_source, "旧関数")
    accepted = project.snapshot()
    assert "Starting Indexing:" not in project.run().stdout
    assert project.snapshot() == accepted
    # A legacy-only refresh must leave the existing modern byte ranges intact.
    legacy_source.write_text("def 旧変更():\n    return 3\n", encoding="utf-8")
    project.run()
    assert "old.旧変更" in project.names() and "old.旧関数" not in project.names()
    project.assert_call("new.caller", "new.新関数")
    updated = project.snapshot()
    project.run(full=True)
    assert project.snapshot() == updated, snapshot_diff(updated, project.snapshot())


@pytest.mark.parametrize("threads", [1, 2])
def test_mixed_legacy_and_modern_same_source_is_rejected_and_retries(tmp_path, threads):
    project = Project(tmp_path / "overlap", "python", f"mixed-ownership-{threads}")
    shared = project.root / "shared"
    shared.mkdir()
    source = shared / "z_source.py"
    source.write_text("def 日本語(引数):\n    return 引数\n", encoding="utf-8")
    _, project.config = configure_project("python", project.root, project.project, options={"source_roots": ["shared"]})
    _indexer_threads(project, threads)
    project.run(full=True)
    accepted = project.snapshot()
    original_settings = project.project.read_bytes()
    _legacy_group(project, source)
    failed = project.run(full=True, success=False)
    assert "Cannot index the same source with legacy Python and a modern adapter" in failed.stdout + failed.stderr
    assert project.snapshot() == accepted
    project.project.write_bytes(original_settings)
    project.run(full=True)
    assert project.snapshot() == accepted
