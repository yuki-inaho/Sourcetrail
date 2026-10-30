"""GRAPH-001: real C++ incremental/clean index correspondence through the CLI."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "semantic_graph", ROOT / "script/verification/semantic_graph.py"
)
assert SPEC is not None and SPEC.loader is not None
GRAPH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAPH)


class CxxProject:
    def __init__(self, directory: Path, executable: Path):
        self.directory = directory
        self.executable = executable
        self.directory.mkdir(parents=True)
        self.project = directory / "fixture.srctrlprj"
        self.home = directory / "isolated-home"
        settings = self.home / ".config/sourcetrail/ApplicationSettings.xml"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<config><version>8</version><indexing>'
            '<indexer_thread_count>1</indexer_thread_count>'
            '<multi_process_indexing>0</multi_process_indexing>'
            '<cxx><has_prefilled_header_search_paths>1</has_prefilled_header_search_paths>'
            '<has_prefilled_framework_search_paths>1</has_prefilled_framework_search_paths>'
            '</cxx></indexing></config>\n', encoding="utf-8",
        )
        self.project.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<config><version>8</version><source_groups><source_group_contract>'
            '<name>Semantic graph contract</name><status>enabled</status>'
            '<type>C/C++ from Compilation Database</type>'
            '<build_file_path><compilation_db_path>compile_commands.json</compilation_db_path>'
            '</build_file_path><indexed_header_paths>'
            '<indexed_header_path>include</indexed_header_path>'
            '</indexed_header_paths></source_group_contract></source_groups></config>\n',
            encoding="utf-8",
        )

    def write(self, relative: str, content: str) -> None:
        path = self.directory / relative
        previous = path.stat().st_mtime_ns if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if previous is not None:
            # Stored modification times have second precision; no wall-clock sleeps are needed.
            os.utime(path, ns=(previous + 2_000_000_000, previous + 2_000_000_000))

    def sources(self, function: str, *, obsolete: bool) -> None:
        self.write("include/api.h", f"""#pragma once
namespace sample {{
int {function}(int value);
double {function}(double value);
}}
""")
        self.write("src/library.cpp", f"""#include "api.h"
namespace sample {{
int {function}(int value) {{ return value + 2; }}
double {function}(double value) {{ return value + 0.5; }}
}}
""")
        self.write("src/main.cpp", f"""#include "api.h"
int main() {{ return sample::{function}(40) + int(sample::{function}(1.5)); }}
""")
        filenames = ["src/main.cpp", "src/library.cpp"]
        if obsolete:
            self.write("src/obsolete.cpp", f"""#include "api.h"
int obsolete_symbol() {{ return sample::{function}(5); }}
""")
            filenames.append("src/obsolete.cpp")
        else:
            (self.directory / "src/obsolete.cpp").unlink(missing_ok=True)
        commands = [
            {"directory": str(self.directory), "file": str(self.directory / filename),
             "arguments": ["clang++", "-std=c++17", "-I", str(self.directory / "include"),
                           "-c", str(self.directory / filename)]}
            for filename in filenames
        ]
        self.write("compile_commands.json", json.dumps(commands))

    def index(self, *, full: bool = False) -> dict:
        environment = os.environ.copy()
        environment.update(
            HOME=str(self.home), QT_QPA_PLATFORM="offscreen", SOURCETRAIL_VIA_SCRIPT="1",
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_DATA_HOME=str(self.home / ".local/share"),
            XDG_CACHE_HOME=str(self.home / ".cache"),
        )
        command = [str(self.executable), "index"]
        if full:
            command.append("--full")
        command.append(str(self.project))
        result = subprocess.run(command, cwd=self.directory, env=environment,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=180)
        # Retain successful-process output too: internal indexing failures can still exit zero.
        print(f"Command: {command!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        assert result.returncode == 0, f"Sourcetrail exited {result.returncode}: {result.stderr}"
        snapshot = GRAPH.read_snapshot(self.project.with_suffix(".srctrldb"), self.directory)
        assert snapshot["nodes"] and snapshot["edges"] and snapshot["locations"]
        assert not snapshot["errors"]
        assert all(row[-2] == 1 for row in snapshot["files"]), snapshot["files"]
        return snapshot


def test_cxx_incremental_update_and_deletion_equal_clean_rebuild(tmp_path):
    executable = Path(os.environ.get("SOURCETRAIL_BINARY", str(ROOT / "build/pixi/app/Sourcetrail"))).resolve()
    assert executable.is_file() and os.access(executable, os.X_OK), (
        f"Required built executable is missing: {executable}; run pixi run build."
    )
    incremental = CxxProject(tmp_path / "incremental 日本語 with spaces", executable)
    incremental.sources("original", obsolete=True)
    initial = incremental.index(full=True)
    assert len(initial["files"]) == 4
    assert "obsolete_symbol" in GRAPH.stable_json(initial)
    assert "(int)" in GRAPH.stable_json(initial) and "(double)" in GRAPH.stable_json(initial)
    assert incremental.index() == initial

    incremental.sources("replacement", obsolete=False)
    updated = incremental.index()
    assert len(updated["files"]) == 3
    assert "original" not in GRAPH.stable_json(updated)
    assert "obsolete_symbol" not in GRAPH.stable_json(updated)
    assert "replacement" in GRAPH.stable_json(updated)

    clean = CxxProject(tmp_path / "clean 日本語 with spaces", executable)
    clean.sources("replacement", obsolete=False)
    rebuilt = clean.index(full=True)
    assert updated == rebuilt, GRAPH.snapshot_diff(updated, rebuilt)
    assert incremental.index() == updated
