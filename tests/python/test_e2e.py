"""Source project -> Sourcetrail CLI -> persisted, postprocessed Python graph."""

import copy
import os
import time
import xml.etree.ElementTree as ET

import pytest

from support import EDGE_INHERITANCE, NODE_CLASS, NODE_FUNCTION, IndexGraph, run_process
from script.verification.semantic_graph import read_snapshot, snapshot_diff


pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("shallow", [True, False], ids=["shallow-postprocessing", "full-jedi"])
def test_python_project_resolves_imports_inheritance_and_qualified_calls(python_project, shallow):
    graph = python_project.index(full=True, shallow=shallow)

    assert not graph.errors
    assert graph.definitions["library.Parent"] == NODE_CLASS
    assert graph.definitions["main.Child"] == NODE_CLASS
    assert graph.definitions["library.helper"] == NODE_FUNCTION
    assert graph.targets("main.Child", EDGE_INHERITANCE) == {"library.Parent"}
    assert graph.targets("main.Child.run") == {"library.Parent.run"}
    assert graph.targets("main.entry") == {"library.helper"}
    assert graph.files == {
        python_project.source_directory / "library.py",
        python_project.source_directory / "main.py",
    }


def test_incremental_reindex_replaces_changed_symbols_and_removes_deleted_files(python_project):
    before = python_project.index(full=True)
    assert "library.helper" in before.definitions
    assert "main.entry" in before.definitions

    library = python_project.source_directory / "library.py"
    original_mtime = library.stat().st_mtime
    library.write_text(
        "def replacement(value):\n"
        "    return value * 2\n"
        "\n"
        "def new_entry():\n"
        "    return replacement(21)\n",
        encoding="utf-8",
    )
    # The application stores timestamps with second precision. No sleep needed.
    # The external indexer records indexing time, which can be newer than a
    # copied fixture's mtime. Advance past both; the former original+2 could
    # accidentally rely on a full-refresh fallback to notice this edit.
    changed_mtime = max(original_mtime, time.time()) + 2
    os.utime(library, (changed_mtime, changed_mtime))
    (python_project.source_directory / "main.py").unlink()

    after = python_project.index()

    assert not after.errors
    assert after.definitions["library.replacement"] == NODE_FUNCTION
    assert after.definitions["library.new_entry"] == NODE_FUNCTION
    assert after.targets("library.new_entry") == {"library.replacement"}
    assert "library.helper" not in after.definitions
    assert "library.Parent" not in after.definitions
    assert not any(name.startswith("main.") for name in after.definitions)
    assert after.files == {library}
    assert not any(
        name.startswith("main.") or name == "library.helper"
        for _, source, target in after.edges for name in (source, target)
    )

    # Re-running unchanged input must preserve the semantic result (IDs may vary).
    assert python_project.index() == after

    # GRAPH-001: compare every schema-25 observation, including signatures,
    # source ranges and ambiguity, with a clean rebuild of the same input.
    database = python_project.project_file.with_suffix(".srctrldb")
    incremental = read_snapshot(database, python_project.project_file.parent)
    python_project.index(full=True)
    clean = read_snapshot(database, python_project.project_file.parent)
    assert incremental == clean, snapshot_diff(incremental, clean)


def test_deleted_file_in_later_nonpartial_group_forces_full_refresh(python_project):
    """SOURCE-GROUP-001: configured ownership includes a removed source path."""
    root = python_project.project_file.parent
    settings = ET.parse(python_project.project_file)
    groups = settings.find("source_groups")
    assert groups is not None and len(groups) == 1
    first = groups[0]
    first.tag = "source_group_aaa"
    first.find("source_paths/source_path").text = "first"
    second = copy.deepcopy(first)
    second.tag = "source_group_zzz"
    second.find("source_paths/source_path").text = "second"
    groups.append(second)
    settings.write(python_project.project_file, encoding="utf-8", xml_declaration=True)
    for folder, filename, symbol in (
        ("first", "keep_a.py", "keep_a"),
        ("second", "keep_b.py", "keep_b"),
        ("second", "remove_me.py", "removed"),
    ):
        directory = root / folder
        directory.mkdir(exist_ok=True)
        (directory / filename).write_text(f"def {symbol}():\n    return 42\n", encoding="utf-8")
    before = python_project.index(full=True)
    assert len(before.files) == 3
    assert "remove_me.removed" in before.definitions
    (root / "second/remove_me.py").unlink()

    # A deletion alone must not rely on a changed surviving file or the first
    # non-partial group accidentally matching. Both surviving files are rebuilt.
    result = run_process(
        [str(python_project.executable), "index", "--shallow", str(python_project.project_file)],
        root, python_project.environment,
    )
    assert "Starting Indexing: 2 source files" in result.stdout
    database = python_project.project_file.with_suffix(".srctrldb")
    after = IndexGraph.read(database)
    assert not after.errors
    assert after.files == {root / "first/keep_a.py", root / "second/keep_b.py"}
    assert {"keep_a.keep_a", "keep_b.keep_b"}.issubset(after.definitions)
    assert not any(name.startswith("remove_me") for name in after.definitions)
    refreshed = read_snapshot(database, root)
    python_project.index(full=True)
    rebuilt = read_snapshot(database, root)
    assert refreshed == rebuilt, snapshot_diff(refreshed, rebuilt)
