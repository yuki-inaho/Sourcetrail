"""Portable graph validation must protect app-owned candidate databases."""

import copy
import sqlite3

import pytest

from script.indexers.graph import GraphError, NODE_KINDS, SCHEMA_SQL, validate_graph, write_graph
from script.verification.semantic_graph import read_snapshot


@pytest.fixture
def graph(tmp_path):
    path = tmp_path / "日本語.py"
    path.write_text("def 日本語():\n    return 1\n", encoding="utf-8")
    return {"files": [{"path": str(path), "content": path.read_text(), "language": "python", "indexed": True, "complete": True}],
            "symbols": [{"id": "fn", "name": ["日本語"], "delimiter": ".", "kind": "function", "definition": "explicit",
                         "locations": [{"file": str(path), "start_line": 1, "start_column": 5, "end_line": 1, "end_column": 13, "kind": "token"}]}],
            "edges": [], "diagnostics": []}


def test_schema25_preserves_content_identity_and_utf8_positions(tmp_path, graph):
    database = tmp_path / "index.db"
    result = write_graph(database, graph)
    assert result == {"files": 1, "symbols": 1, "edges": 0, "diagnostics": 0}
    snapshot = read_snapshot(database, tmp_path)
    assert len(snapshot["files"]) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT definition_kind FROM symbol").fetchall() == [(2,)]
        assert db.execute("SELECT content FROM filecontent").fetchone() == (graph["files"][0]["content"],)
        assert db.execute("SELECT start_column,end_column FROM source_location").fetchall() == [(5, 13)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("damage", ["dangling", "byte-start", "byte-end", "past-eof", "reversed", "nul", "identity", "kind", "version", "name"])
def test_invalid_output_is_rejected_before_database_creation(tmp_path, graph, damage):
    if damage == "dangling":
        graph["edges"].append({"source": "fn", "target": "missing", "kind": "call", "locations": []})
    elif damage in ("byte-start", "byte-end", "past-eof", "reversed"):
        location = graph["symbols"][0]["locations"][0]
        location.update({"byte-start": {"start_column": 6}, "byte-end": {"end_column": 12},
                         "past-eof": {"end_line": 100}, "reversed": {"start_column": 14}}[damage])
    elif damage == "nul":
        graph["files"][0]["content"] += "\x00"
    elif damage == "identity":
        symbol = copy.deepcopy(graph["symbols"][0])
        symbol["id"] = "another"
        graph["symbols"].append(symbol)
    elif damage == "kind":
        graph["symbols"][0]["kind"] = "invented"
    elif damage == "name":
        graph["symbols"][0]["name"] = ["bad\tnname"]
    database = tmp_path / "rejected.db"
    with pytest.raises(GraphError):
        write_graph(database, graph, expected_version=26 if damage == "version" else 25)
    assert not database.exists()


def test_unknown_existing_schema_is_not_modified(tmp_path, graph):
    database = tmp_path / "foreign.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE private_data(value TEXT)")
        db.execute("INSERT INTO private_data VALUES ('preserve')")
    before = database.read_bytes()
    with pytest.raises(GraphError, match="unknown schema"):
        write_graph(database, graph)
    assert database.read_bytes() == before


def test_conflicting_content_rolls_back_the_whole_transaction(tmp_path, graph):
    database = tmp_path / "index.db"
    write_graph(database, graph)
    before = read_snapshot(database, tmp_path)
    graph["files"][0]["content"] += "# different owner\n"
    with pytest.raises(GraphError, match="Conflicting"):
        write_graph(database, graph)
    assert read_snapshot(database, tmp_path) == before


def test_duplicate_injection_has_stable_semantics(tmp_path, graph):
    database = tmp_path / "index.db"
    write_graph(database, graph)
    before = read_snapshot(database, tmp_path)
    write_graph(database, graph)
    assert read_snapshot(database, tmp_path) == before


def test_empty_file_is_distinct_from_a_missing_file(tmp_path):
    source = tmp_path / "empty.py"
    source.write_bytes(b"")
    graph = {"files": [{"path": str(source), "content": "", "language": "python"}], "symbols": [], "edges": [], "diagnostics": []}
    write_graph(tmp_path / "empty.db", graph)
    with sqlite3.connect(tmp_path / "empty.db") as db:
        assert db.execute("SELECT content FROM filecontent").fetchall() == [("",)]
        assert db.execute("SELECT line_count FROM file").fetchall() == [(0,)]


def test_crlf_sources_use_the_existing_lf_storage_convention(tmp_path, graph):
    graph["files"][0]["content"] = graph["files"][0]["content"].replace("\n", "\r\n")
    database = tmp_path / "crlf.db"
    write_graph(database, graph)
    with sqlite3.connect(database) as db:
        assert "\r" not in db.execute("SELECT content FROM filecontent").fetchone()[0]
        assert db.execute("SELECT start_column,end_column FROM source_location").fetchall() == [(5, 13)]


def test_duplicate_injection_keeps_diagnostics_idempotent(tmp_path, graph):
    graph["diagnostics"] = [{"file": graph["files"][0]["path"], "message": "unresolved fixture", "line": 1, "column": 1}]
    database = tmp_path / "diagnostic.db"
    write_graph(database, graph)
    before = read_snapshot(database, tmp_path)
    write_graph(database, graph)
    assert read_snapshot(database, tmp_path) == before
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM error").fetchone() == (1,)


def test_native_name_lookup_cannot_distinguish_colliding_kinds(graph):
    other = copy.deepcopy(graph["symbols"][0])
    other.update(id="different", kind="global_variable")
    graph["symbols"].append(other)
    with pytest.raises(GraphError, match="collide"):
        validate_graph(graph)


def test_separate_groups_cannot_inject_conflicting_name_kinds(tmp_path, graph):
    database = tmp_path / "mixed.db"
    write_graph(database, graph)
    before = database.read_bytes()
    graph["symbols"][0].update(id="another-group", kind="global_variable")
    with pytest.raises(GraphError, match="collid"):
        write_graph(database, graph)
    assert database.read_bytes() == before


def test_separate_groups_cannot_merge_distinct_explicit_definitions(tmp_path, graph):
    database = tmp_path / "distinct-definitions.db"
    write_graph(database, graph)
    before = database.read_bytes()
    another = tmp_path / "other.py"
    another.write_text(graph["files"][0]["content"], encoding="utf-8")
    graph["files"][0]["path"] = str(another)
    graph["symbols"][0]["locations"][0]["file"] = str(another)
    with pytest.raises(GraphError, match="definition"):
        write_graph(database, graph)
    assert database.read_bytes() == before


@pytest.mark.parametrize("kind", ["namespace", "module"])
def test_separate_groups_can_extend_a_shared_container(tmp_path, graph, kind):
    database = tmp_path / "shared-container.db"
    graph["symbols"][0]["kind"] = kind
    write_graph(database, graph)
    another = tmp_path / "other.py"
    another.write_text(graph["files"][0]["content"], encoding="utf-8")
    graph["files"][0]["path"] = str(another)
    graph["symbols"][0]["locations"][0]["file"] = str(another)
    write_graph(database, graph)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM node WHERE type=?", (NODE_KINDS[kind],)).fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM occurrence").fetchone() == (2,)


def test_existing_duplicate_names_are_rejected_without_mutation(tmp_path, graph):
    database = tmp_path / "duplicate.db"
    write_graph(database, graph)
    with sqlite3.connect(database) as db:
        duplicate = db.execute("INSERT INTO element DEFAULT VALUES").lastrowid
        name = db.execute("SELECT serialized_name FROM node WHERE type=?", (NODE_KINDS["function"],)).fetchone()[0]
        db.execute("INSERT INTO node VALUES (?,?,?)", (duplicate, NODE_KINDS["function"], name))
    before = database.read_bytes()
    with pytest.raises(GraphError, match="duplicate|collid"):
        write_graph(database, graph)
    assert database.read_bytes() == before


def test_same_columns_without_foreign_keys_are_not_a_valid_candidate(tmp_path, graph):
    database = tmp_path / "missing-constraints.db"
    schema = SCHEMA_SQL.replace("FOREIGN KEY(id) REFERENCES element(id) ON DELETE CASCADE", "CHECK (id > 0)")
    with sqlite3.connect(database) as db:
        db.executescript(schema)
        db.execute("INSERT INTO meta(key,value) VALUES ('storage_version','25')")
        db.execute("INSERT INTO node VALUES (999,1,'orphan')")
    before = database.read_bytes()
    with pytest.raises(GraphError, match="constraint"):
        write_graph(database, graph)
    assert database.read_bytes() == before


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_observers_preserve_indexed_and_incomplete_flags(tmp_path, graph, reverse):
    database = tmp_path / "flags.db"
    other = copy.deepcopy(graph)
    graph["files"][0].update(indexed=True, complete=False)
    other["files"][0].update(indexed=False, complete=True)
    for current in ([other, graph] if reverse else [graph, other]):
        write_graph(database, current)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT indexed,complete FROM file").fetchall() == [(1, 0)]


def test_conflicting_file_languages_roll_back(tmp_path, graph):
    database = tmp_path / "languages.db"
    write_graph(database, graph)
    before = database.read_bytes()
    graph["files"][0]["language"] = "cpp"
    with pytest.raises(GraphError, match="language"):
        write_graph(database, graph)
    assert database.read_bytes() == before


def test_non_newline_unicode_separators_do_not_add_source_lines(tmp_path, graph):
    graph["files"][0]["content"] = "# A\u0085B\u2028C\vD\fE\n"
    graph["symbols"] = []
    database = tmp_path / "line-count.db"
    write_graph(database, graph)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT line_count FROM file").fetchone() == (1,)


def test_crlf_diagnostic_eof_anchor_maps_to_lf(tmp_path, graph):
    graph["files"][0]["content"] = "日本\r\n"
    graph["symbols"] = []
    graph["diagnostics"] = [{"file": graph["files"][0]["path"], "message": "at physical line end", "line": 1, "column": 8}]
    database = tmp_path / "crlf-diagnostic.db"
    write_graph(database, graph)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT start_column,end_column FROM source_location").fetchall() == [(7, 7)]


@pytest.mark.parametrize("column", [3, 4])
def test_crlf_scope_points_do_not_reverse_or_escape_the_line(tmp_path, graph, column):
    graph["files"][0]["content"] = "ab\r\n"
    graph["symbols"][0]["locations"][0].update(start_column=column, end_column=column, kind="scope")
    database = tmp_path / "crlf-scope.db"
    write_graph(database, graph)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT start_column,end_column FROM source_location").fetchall() == [(3, 3)]


@pytest.mark.parametrize("damage", ["file-shape", "symbol-shape", "edge-shape", "diagnostic-shape", "kind-type",
                                    "locations-type", "diagnostic-fatal", "diagnostic-nul", "name-unicode"])
def test_malformed_graph_types_fail_before_creating_database(tmp_path, graph, damage):
    if damage.endswith("-shape"):
        graph[{"file-shape": "files", "symbol-shape": "symbols", "edge-shape": "edges", "diagnostic-shape": "diagnostics"}[damage]].append(None)
    elif damage == "kind-type":
        graph["symbols"][0]["kind"] = []
    elif damage == "locations-type":
        graph["symbols"][0]["locations"] = None
    elif damage in ("diagnostic-fatal", "diagnostic-nul"):
        graph["diagnostics"].append({"file": graph["files"][0]["path"], "message": "bad\x00message" if damage.endswith("nul") else "bad fatal",
                                     "fatal": False if damage.endswith("nul") else "false"})
    else:
        graph["symbols"][0]["name"] = ["invalid\ud800"]
    database = tmp_path / "malformed.db"
    with pytest.raises(GraphError):
        write_graph(database, graph)
    assert not database.exists()
