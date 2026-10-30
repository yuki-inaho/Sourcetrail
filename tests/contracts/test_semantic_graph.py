"""Independent schema-25 fixtures exercise the exact observation boundary (GRAPH-001)."""

from __future__ import annotations

from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "script/verification/semantic_graph.py"
SPEC = importlib.util.spec_from_file_location("semantic_graph", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GRAPH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAPH)

# Written independently from the exporter's SCHEMA constant. Column order follows
# SqliteIndexStorage::setupTables; constraints make fixture mistakes visible.
SCHEMA_SQL = """
CREATE TABLE meta(id INTEGER PRIMARY KEY, key TEXT, value TEXT);
CREATE TABLE element(id INTEGER PRIMARY KEY);
CREATE TABLE node(id INTEGER PRIMARY KEY, type INTEGER NOT NULL, serialized_name TEXT,
                  FOREIGN KEY(id) REFERENCES element(id));
CREATE TABLE symbol(id INTEGER PRIMARY KEY, definition_kind INTEGER NOT NULL,
                    FOREIGN KEY(id) REFERENCES node(id));
CREATE TABLE edge(id INTEGER PRIMARY KEY, type INTEGER NOT NULL,
                  source_node_id INTEGER NOT NULL, target_node_id INTEGER NOT NULL,
                  FOREIGN KEY(id) REFERENCES element(id),
                  FOREIGN KEY(source_node_id) REFERENCES node(id),
                  FOREIGN KEY(target_node_id) REFERENCES node(id));
CREATE TABLE file(id INTEGER PRIMARY KEY, path TEXT, language TEXT, modification_time TEXT,
                  indexed INTEGER, complete INTEGER, line_count INTEGER,
                  FOREIGN KEY(id) REFERENCES node(id));
CREATE TABLE filecontent(id INTEGER PRIMARY KEY, content TEXT,
                         FOREIGN KEY(id) REFERENCES file(id));
CREATE TABLE local_symbol(id INTEGER PRIMARY KEY, name TEXT,
                          FOREIGN KEY(id) REFERENCES element(id));
CREATE TABLE source_location(id INTEGER PRIMARY KEY, file_node_id INTEGER,
                             start_line INTEGER, start_column INTEGER,
                             end_line INTEGER, end_column INTEGER, type INTEGER,
                             FOREIGN KEY(file_node_id) REFERENCES node(id));
CREATE TABLE occurrence(element_id INTEGER NOT NULL, source_location_id INTEGER NOT NULL,
                        PRIMARY KEY(element_id, source_location_id),
                        FOREIGN KEY(element_id) REFERENCES element(id),
                        FOREIGN KEY(source_location_id) REFERENCES source_location(id));
CREATE TABLE component_access(node_id INTEGER PRIMARY KEY, type INTEGER NOT NULL,
                              FOREIGN KEY(node_id) REFERENCES node(id));
CREATE TABLE element_component(id INTEGER PRIMARY KEY, element_id INTEGER, type INTEGER, data TEXT,
                               FOREIGN KEY(element_id) REFERENCES element(id));
CREATE TABLE error(id INTEGER PRIMARY KEY, message TEXT, fatal INTEGER NOT NULL,
                   indexed INTEGER NOT NULL, translation_unit TEXT,
                   FOREIGN KEY(id) REFERENCES element(id));
"""


def make_index(path: Path, project_root: Path, *, id_offset: int = 0,
               reverse_rows: bool = False, timestamp: str = "2000-01-01 00:00:00") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    source = (project_root / "main.cpp").as_posix()
    row_id = lambda value: value + id_offset
    values = {
        "meta": [(1, "storage_version", "25"), (2, "project_settings", "fixture")],
        "element": [(row_id(value),) for value in range(1, 8)],
        "node": [
            (row_id(1), 1 << 18, f"/\tm{source}\ts\tp"),
            (row_id(2), 1 << 12, "::\tmuse\tsint \tp()"),
            (row_id(3), 1 << 12, "::\tmtarget\tsint \tp(int)"),
            (row_id(4), 1 << 12, "::\tmtarget\tsdouble \tp(double)"),
        ],
        "symbol": [(row_id(value), 1) for value in (2, 3, 4)],
        "edge": [(row_id(5), 1 << 3, row_id(2), row_id(3))],
        "file": [(row_id(1), source, "C++", timestamp, 1, 0, 4)],
        "filecontent": [(row_id(1), "int target(int value);\nint use() { return target(1); }\n")],
        "local_symbol": [(row_id(6), f"value@{source}")],
        "source_location": [
            (row_id(101), row_id(1), 1, 5, 1, 10, 0),
            (row_id(102), row_id(1), 2, 20, 2, 25, 0),
            (row_id(103), row_id(1), 1, 16, 1, 20, 2),
            (row_id(104), row_id(1), 4, 1, 4, 2, 0),
        ],
        "occurrence": [(row_id(element), row_id(location))
                       for element, location in ((3, 101), (5, 102), (6, 103), (7, 104))],
        "component_access": [(row_id(3), 1)],
        "element_component": [(row_id(201), row_id(5), 1, "ambiguous")],
        "error": [(row_id(7), f"diagnostic in {source}", 0, 1, source)],
    }
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA_SQL)
        for table, rows in values.items():
            if reverse_rows:
                rows = list(reversed(rows))
            placeholders = ",".join("?" for _ in rows[0])
            db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        db.commit()
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    return path


def mutate(path: Path, sql: str, parameters: tuple = ()) -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute(sql, parameters)
        db.commit()


def snapshot(path: Path, root: Path) -> dict:
    return GRAPH.read_snapshot(path, root)


def test_ids_root_relocation_row_order_and_timestamps_are_not_observations(tmp_path):
    left_root, right_root = tmp_path / "left 日本語", tmp_path / "right with spaces"
    left = make_index(tmp_path / "left.db", left_root)
    right = make_index(tmp_path / "right.db", right_root, id_offset=1000,
                       reverse_rows=True, timestamp="2099-12-31 23:59:59")
    assert snapshot(left, left_root) == snapshot(right, right_root)
    assert "target" in GRAPH.stable_json(snapshot(left, left_root))
    assert "(int)" in GRAPH.stable_json(snapshot(left, left_root))
    assert "(double)" in GRAPH.stable_json(snapshot(left, left_root))


@pytest.mark.parametrize("sql,parameters,observation", [
    ("UPDATE node SET serialized_name=? WHERE id=4", ("::\tmtarget\tsfloat \tp(float)",), "nodes"),
    ("UPDATE node SET type=8192 WHERE id=3", (), "nodes"),
    ("UPDATE symbol SET definition_kind=2 WHERE id=3", (), "symbols"),
    ("UPDATE edge SET source_node_id=3,target_node_id=2 WHERE id=5", (), "edges"),
    ("UPDATE edge SET type=4 WHERE id=5", (), "edges"),
    ("UPDATE source_location SET start_column=6 WHERE id=101", (), "locations"),
    ("UPDATE occurrence SET source_location_id=102 WHERE element_id=3", (), "occurrences"),
    ("UPDATE error SET message='different diagnostic' WHERE id=7", (), "errors"),
    ("UPDATE error SET fatal=1 WHERE id=7", (), "errors"),
    ("UPDATE element_component SET data='unambiguous' WHERE id=201", (), "components"),
    ("UPDATE element_component SET type=2 WHERE id=201", (), "components"),
    ("UPDATE component_access SET type=2 WHERE node_id=3", (), "access"),
    ("UPDATE file SET complete=1 WHERE id=1", (), "files"),
    ("UPDATE file SET indexed=0 WHERE id=1", (), "files"),
    ("UPDATE file SET language='Python' WHERE id=1", (), "files"),
    ("UPDATE file SET line_count=5 WHERE id=1", (), "files"),
    ("UPDATE filecontent SET content='changed source literal' WHERE id=1", (), "file_contents"),
    ("UPDATE local_symbol SET name='renamed local' WHERE id=6", (), "local_symbols"),
])
def test_semantic_changes_are_observed(tmp_path, sql, parameters, observation):
    root = tmp_path / "project"
    database = make_index(tmp_path / "index.db", root)
    before = snapshot(database, root)
    mutate(database, sql, parameters)
    after = snapshot(database, root)
    assert before[observation] != after[observation]
    assert GRAPH.snapshot_diff(before, after).startswith("--- before\n+++ after\n")


def test_content_is_not_path_normalized(tmp_path):
    roots = (tmp_path / "one", tmp_path / "two")
    databases = [make_index(tmp_path / f"{index}.db", root)
                 for index, root in enumerate(roots)]
    for root, database in zip(roots, databases):
        mutate(database, "UPDATE filecontent SET content=?", (f'const char* path="{root}/data";',))
    assert snapshot(databases[0], roots[0])["file_contents"] != snapshot(databases[1], roots[1])["file_contents"]
    mutate(databases[0], "UPDATE filecontent SET content=?", ("${PROJECT_ROOT}",))
    assert snapshot(databases[0], roots[0])["file_contents"]


@pytest.mark.parametrize("sql,observation", [
    ("INSERT INTO source_location SELECT 105,file_node_id,start_line,start_column,end_line,end_column,type "
     "FROM source_location WHERE id=101", "locations"),
    ("INSERT INTO element_component SELECT 202,element_id,type,data FROM element_component WHERE id=201", "components"),
])
def test_fact_multiplicity_is_preserved(tmp_path, sql, observation):
    root = tmp_path / "project"
    database = make_index(tmp_path / "index.db", root)
    before = snapshot(database, root)
    mutate(database, sql)
    after = snapshot(database, root)
    assert len(after[observation]) == len(before[observation]) + 1
    assert before != after


def test_normalization_respects_root_boundaries(tmp_path):
    root = tmp_path / "project+[x]"
    normal = GRAPH.Normalizer(root)
    assert normal.text(f"{root}/main.cpp") == "${PROJECT_ROOT}/main.cpp"
    assert normal.text(f"'{root}/main.cpp': error") == "'${PROJECT_ROOT}/main.cpp': error"
    for untouched in (f"{root}-other/main.cpp", f"{root}suffix/main.cpp", f"/prefix{root}/main.cpp"):
        assert normal.text(untouched) == untouched
    with pytest.raises(GRAPH.SnapshotError):
        GRAPH.Normalizer(Path("/"))


def test_main_identity_normalizes_its_encoded_file_path_without_merging_files(tmp_path):
    # CxxAstVisitorComponentIndexer prefixes a main declaration with '.:main:.' and
    # its absolute source path. Preserve that file identity while allowing relocation.
    left, right = tmp_path / "left", tmp_path / "right"
    left_name = GRAPH.Normalizer(left).name(f"::\tm.:main:.{left}/one.cpp\tsint \tp()")
    right_name = GRAPH.Normalizer(right).name(f"::\tm.:main:.{right}/one.cpp\tsint \tp()")
    different_file = GRAPH.Normalizer(right).name(f"::\tm.:main:.{right}/two.cpp\tsint \tp()")
    assert left_name == right_name
    assert right_name != different_file


@pytest.mark.parametrize("sql,parameters", [
    ("UPDATE meta SET value='26' WHERE key='storage_version'", ()),
    ("CREATE TABLE unmodelled_feature(id INTEGER)", ()),
    ("ALTER TABLE node ADD COLUMN unmodelled_feature TEXT", ()),
    ("DROP TABLE symbol", ()),
    ("UPDATE node SET serialized_name='not a hierarchy' WHERE id=3", ()),
    ("UPDATE node SET serialized_name='::' || char(9) || 'mname' WHERE id=3", ()),
    ("UPDATE node SET serialized_name=? WHERE id=3", ("::\tm${PROJECT_ROOT}\ts\tp",)),
    ("UPDATE edge SET target_node_id=99999 WHERE id=5", ()),
    ("UPDATE occurrence SET source_location_id=99999 WHERE element_id=5", ()),
    ("UPDATE source_location SET file_node_id=2 WHERE id=101", ()),
    ("UPDATE element_component SET element_id=99999 WHERE id=201", ()),
    ("DELETE FROM element WHERE id=3", ()),
])
def test_invalid_or_unmodelled_databases_fail_closed(tmp_path, sql, parameters):
    root = tmp_path / "project"
    database = make_index(tmp_path / "index.db", root)
    mutate(database, sql, parameters)
    with pytest.raises(GRAPH.SnapshotError):
        snapshot(database, root)


def test_duplicate_numeric_ids_in_malformed_table_are_not_silently_overwritten(tmp_path):
    root = tmp_path / "project"
    database = make_index(tmp_path / "index.db", root)
    with closing(sqlite3.connect(database)) as db:
        # Preserve column names but deliberately remove the PK. A damaged semantic input must
        # not be converted into an apparently valid dict by overwriting duplicate IDs.
        db.executescript("""
            CREATE TABLE local_replacement(id INTEGER, name TEXT);
            INSERT INTO local_replacement SELECT * FROM local_symbol;
            INSERT INTO local_replacement SELECT * FROM local_symbol WHERE id=6;
            DROP TABLE local_symbol;
            ALTER TABLE local_replacement RENAME TO local_symbol;
        """)
    with pytest.raises(GRAPH.SnapshotError, match="Duplicate numeric"):
        snapshot(database, root)


def test_allocator_only_rows_are_ignored_but_cannot_be_referenced_as_facts(tmp_path):
    # SqliteIndexStorage::addSourceLocations allocates an element row separately from the
    # source_location row ID. Such untyped/unreferenced allocations have no graph meaning.
    root = tmp_path / "project"
    database = make_index(tmp_path / "index.db", root)
    before = snapshot(database, root)
    mutate(database, "INSERT INTO element VALUES (99999)")
    assert snapshot(database, root) == before
    mutate(database, "INSERT INTO occurrence VALUES (99999,101)")
    with pytest.raises(GRAPH.SnapshotError, match="Dangling"):
        snapshot(database, root)


def test_missing_and_non_sqlite_files_fail_without_creating_a_database(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(GRAPH.SnapshotError):
        snapshot(missing, tmp_path)
    assert not missing.exists()
    malformed = tmp_path / "broken.db"
    malformed.write_bytes(b"this is not sqlite")
    with pytest.raises(GRAPH.SnapshotError):
        snapshot(malformed, tmp_path)


def test_duplicate_semantic_node_identity_is_rejected(tmp_path):
    root = tmp_path / "project"
    database = make_index(tmp_path / "index.db", root)
    mutate(database, "UPDATE node SET serialized_name=(SELECT serialized_name FROM node WHERE id=3) WHERE id=4")
    with pytest.raises(GRAPH.SnapshotError, match="duplicate"):
        snapshot(database, root)


def test_cli_exit_codes_and_export(tmp_path):
    root = tmp_path / "project"
    left = make_index(tmp_path / "left.db", root)
    right = make_index(tmp_path / "right.db", root, id_offset=1000)
    command = [sys.executable, str(SCRIPT), "compare", str(left), str(right),
               "--before-root", str(root), "--after-root", str(root)]
    equal = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert equal.returncode == 0, equal.stderr
    assert "Equivalent" in equal.stdout
    mutate(right, "UPDATE file SET complete=1")
    changed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert changed.returncode == 1, changed.stderr
    assert "--- before" in changed.stdout and "+++ after" in changed.stdout
    right.unlink()
    invalid = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert invalid.returncode == 2
    assert "Cannot compare" in invalid.stderr
    assert not right.exists()
    output = tmp_path / "snapshots/export.json"
    exported = subprocess.run([sys.executable, str(SCRIPT), "export", str(left),
                               "--root", str(root), "--output", str(output)],
                              capture_output=True, text=True, timeout=30)
    assert exported.returncode == 0, exported.stderr
    assert json.loads(output.read_text(encoding="utf-8")) == snapshot(left, root)


@pytest.mark.parametrize("output_kind", ["same-path", "symlink-alias", "hardlink-alias"])
def test_export_rejects_input_aliases_without_changing_database_bytes(tmp_path, output_kind):
    root = tmp_path / "project"
    database = make_index(tmp_path / "input.db", root)
    output = database if output_kind == "same-path" else tmp_path / "alias.json"
    if output_kind == "symlink-alias":
        output.symlink_to(database)
    elif output_kind == "hardlink-alias":
        output.hardlink_to(database)
    original_bytes = database.read_bytes()

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "export", str(database),
         "--root", str(root), "--output", str(output)],
        capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "must not overwrite" in result.stderr
    assert database.read_bytes() == original_bytes
    assert output.samefile(database)
    if output_kind == "symlink-alias":
        assert output.is_symlink()
