"""Process and database helpers shared by the Python indexing tests."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import shlex
import sqlite3
import subprocess

import pytest


# These are the on-disk values from src/lib/data/{NodeKind,graph/Edge}.h.
NODE_CLASS = 1 << 7
NODE_FUNCTION = 1 << 12
EDGE_CALL = 1 << 3
EDGE_INHERITANCE = 1 << 4


def qualified_name(serialized: str) -> str:
    """Decode Sourcetrail's name hierarchy without depending on numeric IDs."""
    delimiter, separator, hierarchy = serialized.partition("\tm")
    assert separator, f"Invalid serialized name: {serialized!r}"
    names = []
    for part in hierarchy.split("\tn"):
        name, separator, signature = part.partition("\ts")
        assert separator and "\tp" in signature, f"Invalid name part: {part!r}"
        names.append(name)
    return delimiter.join(names)


@dataclass(frozen=True)
class IndexGraph:
    """Semantic snapshot of a database produced by a completed process."""

    definitions: dict[str, int]
    edges: frozenset[tuple[int, str, str]]
    files: frozenset[Path]
    errors: tuple[str, ...]
    definition_lines: dict[str, frozenset[int]]

    @classmethod
    def read(cls, database: Path) -> "IndexGraph":
        assert database.is_file(), f"Indexer did not create {database}"
        # Read-only mode prevents an absent database from becoming an empty one.
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            assert db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            version = db.execute(
                "SELECT value FROM meta WHERE key = 'storage_version'"
            ).fetchone()
            assert version == ("25",), f"Unexpected index schema version: {version!r}"
            definitions = {
                qualified_name(name): kind
                for name, kind in db.execute(
                    "SELECT node.serialized_name, node.type FROM node "
                    "JOIN symbol ON symbol.id = node.id"
                )
            }
            edges = frozenset(
                (kind, qualified_name(source), qualified_name(target))
                for kind, source, target in db.execute(
                    "SELECT edge.type, source.serialized_name, target.serialized_name "
                    "FROM edge JOIN node AS source ON source.id = edge.source_node_id "
                    "JOIN node AS target ON target.id = edge.target_node_id"
                )
            )
            files = frozenset(
                Path(path).resolve()
                for (path,) in db.execute("SELECT path FROM file WHERE indexed = 1")
            )
            errors = tuple(message for (message,) in db.execute("SELECT message FROM error"))
            lines: dict[str, set[int]] = {}
            for name, line in db.execute(
                "SELECT node.serialized_name, source_location.start_line "
                "FROM node JOIN occurrence ON occurrence.element_id = node.id "
                "JOIN source_location ON source_location.id = occurrence.source_location_id"
            ):
                lines.setdefault(qualified_name(name), set()).add(line)
        return cls(
            definitions, edges, files, errors,
            {name: frozenset(numbers) for name, numbers in lines.items()},
        )

    def targets(self, source: str, kind: int = EDGE_CALL) -> frozenset[str]:
        return frozenset(target for edge_kind, origin, target in self.edges
                         if edge_kind == kind and origin == source)


def run_process(arguments: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run a real command and include both output streams in failure reports."""
    try:
        result = subprocess.run(
            arguments, cwd=cwd, env=environment, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        pytest.fail(
            f"Command timed out: {arguments!r}\n"
            f"stdout:\n{error.stdout}\nstderr:\n{error.stderr}",
            pytrace=False,
        )
    assert result.returncode == 0, (
        f"Command failed ({result.returncode}): {arguments!r}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # pytest retains this output and includes it if a later graph assertion fails.
    # The application can exit successfully even when an internal indexer fails.
    print(f"Command: {shlex.join(arguments)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


@dataclass(frozen=True)
class PythonIndexer:
    executable: Path
    work_directory: Path
    environment: dict[str, str]
    python_environment: Path

    def index(self, source: str, filename: str = "sample.py") -> IndexGraph:
        source_file = self.work_directory / filename
        source_file.write_text(source, encoding="utf-8")
        database = self.work_directory / "index.srctrldb"
        run_process(
            [str(self.executable), "index", "--source-file-path", str(source_file),
             "--database-file-path", str(database),
             "--environment-path", str(self.python_environment)],
            self.work_directory, self.environment,
        )
        return IndexGraph.read(database)


@dataclass(frozen=True)
class SourcetrailProject:
    executable: Path
    project_file: Path
    environment: dict[str, str]

    @property
    def source_directory(self) -> Path:
        return self.project_file.parent / "src"

    def index(self, *, full: bool = False, shallow: bool = True) -> IndexGraph:
        arguments = [str(self.executable), "index"]
        if shallow:
            arguments.append("--shallow")
        if full:
            arguments.append("--full")
        arguments.append(str(self.project_file))
        run_process(arguments, self.project_file.parent, self.environment)
        return IndexGraph.read(self.project_file.with_suffix(".srctrldb"))
