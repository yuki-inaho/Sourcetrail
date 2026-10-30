"""Source project -> Sourcetrail CLI -> persisted, postprocessed Python graph."""

import os

import pytest

from support import EDGE_INHERITANCE, NODE_CLASS, NODE_FUNCTION


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
    os.utime(library, (original_mtime + 2, original_mtime + 2))
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
