"""Real-app regressions discovered by reviewing the adapter/native boundary."""

import json
import os

from test_app_e2e import Project


def test_excluded_directory_names_above_the_source_root_do_not_hide_sources(tmp_path):
    project = Project(tmp_path / "build" / "project", "python", "review-exclude-parent")
    (project.root / "main.py").write_text("def kept():\n    return 1\n")
    (project.root / "build").mkdir()
    (project.root / "build/ignored.py").write_text("def omitted():\n    return 2\n")
    project.configure()
    project.run(full=True)
    assert "main.kept" in project.names()
    assert not any("omitted" in name for name in project.names())
    accepted = project.snapshot()
    assert "Starting Indexing:" not in project.run().stdout
    assert project.snapshot() == accepted


def test_cdb_unselected_inputs_do_not_reindex_an_unchanged_project(tmp_path):
    project = Project(tmp_path / "unselected", "cpp", "review-cdb-unselected")
    source = project.root / "main.cpp"
    source.write_text("int keep(){return 1;}\n")
    (project.root / "unselected.cpp").write_text("outside this compilation configuration\n")
    (project.root / "unused.hpp").write_text("unused header\n")
    (project.root / "compile_commands.json").write_text(json.dumps([
        {"directory": str(project.root), "file": str(source), "arguments": ["clang++", "-std=c++23", "-c", str(source)]}]))
    project.configure()
    project.run(full=True)
    accepted = project.snapshot()
    assert "keep" in project.names()
    assert "Starting Indexing:" not in project.run().stdout
    assert project.snapshot() == accepted


def test_external_response_preserves_noop_and_refreshes_same_time_content_changes(tmp_path):
    project = Project(tmp_path / "response", "cpp", "review-external-response")
    source = project.root / "main.cpp"
    source.write_text("#if MODE == 1\nint before(){return 1;}\n#else\nint after(){return 2;}\n#endif\n")
    response = tmp_path / "external.rsp"
    response.write_text("-DMODE=1\n")
    (project.root / "compile_commands.json").write_text(json.dumps([
        {"directory": str(project.root), "file": str(source),
         "arguments": ["clang++", "@" + str(response), "-std=c++23", "-c", str(source)]}]))
    project.configure()
    project.run(full=True)
    accepted = project.snapshot()
    assert "before" in project.names()
    assert "Starting Indexing:" not in project.run().stdout
    assert project.snapshot() == accepted
    previous = response.stat().st_mtime_ns
    response.write_text("-DMODE=2\n")
    os.utime(response, ns=(previous, previous))
    project.run()
    assert "after" in project.names() and "before" not in project.names()
    changed = project.snapshot()
    project.run(full=True)
    assert project.snapshot() == changed
