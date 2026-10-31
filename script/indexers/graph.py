"""Validate the portable adapter graph and commit it to Sourcetrail schema 25.

Engines do not own database IDs or transactions. All coordinates are one-based,
inclusive UTF-8 byte coordinates in the exact stored source. Validation runs
before opening the output database, and every write is one SQLite transaction.
"""

from __future__ import annotations

from contextlib import closing
import copy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any


PROTOCOL_VERSION = 1
DATABASE_VERSION = 25
NODE_KINDS = {name: 1 << index for index, name in enumerate((
    "symbol", "type", "builtin_type", "module", "namespace", "package", "struct",
    "class", "interface", "annotation", "global_variable", "field", "function",
    "method", "enum", "enum_constant", "typedef", "type_parameter", "file", "macro", "union",
))}
EDGE_KINDS = {name: 1 << index for index, name in enumerate((
    "member", "type_usage", "usage", "call", "inheritance", "override", "type_argument",
    "template_specialization", "include", "import", "bundled_edges", "macro_usage",
    "annotation_usage",
))}
LOCATION_KINDS = {name: index for index, name in enumerate((
    "token", "scope", "qualifier", "local_symbol", "signature", "comment", "error",
    "fulltext_search", "screen_search", "unsolved",
))}
DEFINITIONS = {"none": 0, "implicit": 1, "explicit": 2}


class GraphError(ValueError):
    """The adapter output cannot be represented without losing its meaning."""


def empty_graph() -> dict[str, list]:
    return {key: [] for key in ("files", "symbols", "edges", "diagnostics")}


def _utf8_text(value: Any) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def serialized_name(parts: list, delimiter: str = "::") -> str:
    if not isinstance(parts, list) or not parts:
        raise GraphError("A symbol must have a nonempty name hierarchy")
    encoded = []
    for part in parts:
        if isinstance(part, str):
            part = {"name": part}
        if not isinstance(part, dict):
            raise GraphError("Invalid name element")
        values = [part.get("name"), part.get("prefix", ""), part.get("postfix", "")]
        if not values[0] or any(not _utf8_text(v) or "\t" in v for v in values):
            raise GraphError("Names and signatures must be nonempty, unambiguous UTF-8 text")
        encoded.append(values[0] + "\ts" + values[1] + "\tp" + values[2])
    if delimiter not in ("::", ".", "/"):
        raise GraphError(f"Unsupported name delimiter: {delimiter!r}")
    return delimiter + "\tm" + "\tn".join(encoded)


def _absolute_path(value: Any) -> str:
    if not _utf8_text(value) or not value or not Path(value).is_absolute():
        raise GraphError(f"Expected an absolute source path: {value!r}")
    return str(Path(value).resolve())


def _location_key(location: dict) -> tuple:
    return tuple(location[key] for key in (
        "file", "start_line", "start_column", "end_line", "end_column", "kind",
    ))


def canonical_graph(graph: dict) -> dict:
    """Map physical CRLF inputs to Sourcetrail's existing LF storage convention.

    Engines first describe the physical source and the CLI verifies its bytes.
    Removing the CR in CRLF does not shift token columns; a scope which includes
    that CR is shortened explicitly. Standalone CR is rejected by this profile.
    """
    result = copy.deepcopy(graph)
    original = {source["path"]: source["content"].split("\n") for source in result["files"]}
    for source in result["files"]:
        source["content"] = source["content"].replace("\r\n", "\n")
        if "\r" in source["content"]:
            raise GraphError("Modern adapters require LF or CRLF source line endings")
    def relocate(location: dict) -> None:
        lines = original[location["file"]]
        start = lines[location["start_line"] - 1].encode("utf-8")
        end = lines[location["end_line"] - 1].encode("utf-8")
        if start.endswith(b"\r") and location["start_column"] > len(start):
            location["start_column"] -= 1
        if end.endswith(b"\r") and location["end_column"] >= len(end):
            location["end_column"] = max(1, location["end_column"] - 1)
        if (location["start_line"] == location["end_line"]
                and location["end_column"] < location["start_column"]):
            # A point on the removed CR becomes an explicit line-end anchor.
            location["end_column"] = location["start_column"]

    for owner in result["symbols"] + result["edges"]:
        for location in owner.get("locations", []):
            relocate(location)
    for diagnostic in result["diagnostics"]:
        location = {"file": diagnostic["file"], "start_line": diagnostic.get("line", 1),
                    "end_line": diagnostic.get("line", 1), "start_column": diagnostic.get("column", 1),
                    "end_column": diagnostic.get("end_column", diagnostic.get("column", 1))}
        relocate(location)
        diagnostic.update(column=location["start_column"], end_column=location["end_column"])
    return result


def validate_graph(graph: dict) -> None:
    """Fail closed on broken identity, dangling edges and impossible positions."""
    if not isinstance(graph, dict) or any(not isinstance(graph.get(k), list) for k in (
        "files", "symbols", "edges", "diagnostics",
    )):
        raise GraphError("An adapter graph requires files, symbols, edges and diagnostics lists")
    if any(not isinstance(item, dict) for key in ("files", "symbols", "edges", "diagnostics") for item in graph[key]):
        raise GraphError("Adapter graph entries must be objects")
    files: dict[str, dict] = {}
    for source in graph["files"]:
        path = _absolute_path(source.get("path"))
        if path != source["path"] or path in files:
            raise GraphError(f"Duplicate or noncanonical file: {path}")
        serialized_name([path], "/")  # File nodes use the same delimiter-encoded name format.
        content = source.get("content")
        if not isinstance(content, str) or "\x00" in content:
            raise GraphError(f"Invalid UTF-8 source content: {path}")
        try:
            content.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise GraphError(f"Invalid Unicode source content: {path}") from error
        if source.get("language") not in ("python", "cpp", "rust", "config", "Python", "C++", "Rust"):
            raise GraphError(f"Unknown file language: {source.get('language')!r}")
        for flag in ("indexed", "complete"):
            if not isinstance(source.get(flag, True), bool):
                raise GraphError(f"File {flag} must be boolean")
        files[path] = source

    def location(value: dict) -> None:
        if not isinstance(value, dict) or not isinstance(value.get("file"), str) or value["file"] not in files:
            raise GraphError("A location refers to a file absent from the graph")
        kind = value.get("kind", "token")
        if not isinstance(kind, str) or kind not in LOCATION_KINDS:
            raise GraphError(f"Unknown location kind: {kind}")
        coordinates = [value.get(k) for k in ("start_line", "start_column", "end_line", "end_column")]
        if any(type(v) is not int or v < 1 for v in coordinates):
            raise GraphError(f"Invalid source coordinates: {value}")
        sl, sc, el, ec = coordinates
        if (sl, sc) > (el, ec):
            raise GraphError(f"Reversed source range: {value}")
        # split('\n') preserves EOF and CRLF; columns count stored UTF-8 bytes.
        lines = files[value["file"]]["content"].split("\n")
        for row, column, is_end in ((sl, sc, False), (el, ec, True)):
            if row > len(lines):
                raise GraphError(f"Source line outside content: {value}")
            encoded = lines[row - 1].encode("utf-8")
            boundary = column if is_end else column - 1
            if column > len(encoded):
                # Empty-file diagnostics and scope EOF anchors are explicit points.
                if column == len(encoded) + 1 and kind in ("scope", "error", "unsolved"):
                    continue
                raise GraphError(f"Source column outside content: {value}")
            if boundary < len(encoded) and encoded[boundary] & 0xC0 == 0x80:
                raise GraphError(f"Coordinate splits a UTF-8 scalar: {value}")

    ids = {"file:" + path for path in files}
    identities: dict[str, str] = {}
    for symbol in graph["symbols"]:
        identity = symbol.get("id")
        if not _utf8_text(identity) or not identity or identity in ids:
            raise GraphError(f"Duplicate or invalid symbol identity: {identity!r}")
        kind = symbol.get("kind")
        if not isinstance(kind, str) or kind not in NODE_KINDS or kind == "file":
            raise GraphError(f"Unknown symbol kind: {kind!r}")
        if not isinstance(symbol.get("definition", "none"), str) or symbol.get("definition", "none") not in DEFINITIONS:
            raise GraphError("Unknown definition state")
        name = serialized_name(symbol.get("name"), symbol.get("delimiter", "::"))
        # Native name lookup is keyed by hierarchy; different kinds cannot make
        # two distinct symbols with the same serialized hierarchy safe.
        semantic_key = name
        if semantic_key in identities:
            raise GraphError(f"Distinct symbol IDs collide in schema 25: {identity} / {identities[semantic_key]}")
        identities[semantic_key] = identity
        ids.add(identity)
        if symbol.get("access") not in (None, "public", "protected", "private"):
            raise GraphError("Unknown access state")
        if not isinstance(symbol.get("locations", []), list):
            raise GraphError("Symbol locations must be a list")
        for value in symbol.get("locations", []):
            location(value)
    for edge in graph["edges"]:
        if any(not isinstance(edge.get(key), str) or edge[key] not in ids for key in ("source", "target")):
            raise GraphError(f"Dangling graph edge: {edge}")
        if not isinstance(edge.get("kind"), str) or edge["kind"] not in EDGE_KINDS:
            raise GraphError(f"Unknown edge kind: {edge.get('kind')!r}")
        if not isinstance(edge.get("locations", []), list):
            raise GraphError("Edge locations must be a list")
        for value in edge.get("locations", []):
            location(value)
    for diagnostic in graph["diagnostics"]:
        if (not isinstance(diagnostic.get("file"), str) or diagnostic["file"] not in files
                or not _utf8_text(diagnostic.get("message"))):
            raise GraphError("Invalid diagnostic source or message")
        if type(diagnostic.get("fatal", False)) is not bool:
            raise GraphError("Diagnostic fatal must be boolean")
        location({"file": diagnostic["file"], "start_line": diagnostic.get("line", 1),
                  "end_line": diagnostic.get("line", 1), "start_column": diagnostic.get("column", 1),
                  "end_column": diagnostic.get("end_column", diagnostic.get("column", 1)), "kind": "error"})


SCHEMA_SQL = """
CREATE TABLE meta(id INTEGER PRIMARY KEY, key TEXT, value TEXT);
CREATE TABLE element(id INTEGER PRIMARY KEY);
CREATE TABLE node(id INTEGER PRIMARY KEY, type INTEGER NOT NULL, serialized_name TEXT,
 FOREIGN KEY(id) REFERENCES element(id) ON DELETE CASCADE);
CREATE TABLE symbol(id INTEGER PRIMARY KEY, definition_kind INTEGER NOT NULL,
 FOREIGN KEY(id) REFERENCES node(id) ON DELETE CASCADE);
CREATE TABLE edge(id INTEGER PRIMARY KEY, type INTEGER NOT NULL, source_node_id INTEGER NOT NULL,
 target_node_id INTEGER NOT NULL, FOREIGN KEY(id) REFERENCES element(id) ON DELETE CASCADE,
 FOREIGN KEY(source_node_id) REFERENCES node(id) ON DELETE CASCADE,
 FOREIGN KEY(target_node_id) REFERENCES node(id) ON DELETE CASCADE);
CREATE TABLE file(id INTEGER PRIMARY KEY, path TEXT, language TEXT, modification_time TEXT,
 indexed INTEGER, complete INTEGER, line_count INTEGER,
 FOREIGN KEY(id) REFERENCES node(id) ON DELETE CASCADE);
CREATE TABLE filecontent(id INTEGER PRIMARY KEY, content TEXT,
 FOREIGN KEY(id) REFERENCES file(id) ON DELETE CASCADE ON UPDATE CASCADE);
CREATE TABLE local_symbol(id INTEGER PRIMARY KEY, name TEXT,
 FOREIGN KEY(id) REFERENCES element(id) ON DELETE CASCADE);
CREATE TABLE source_location(id INTEGER PRIMARY KEY, file_node_id INTEGER, start_line INTEGER,
 start_column INTEGER, end_line INTEGER, end_column INTEGER, type INTEGER,
 FOREIGN KEY(file_node_id) REFERENCES node(id) ON DELETE CASCADE);
CREATE TABLE occurrence(element_id INTEGER NOT NULL, source_location_id INTEGER NOT NULL,
 PRIMARY KEY(element_id, source_location_id), FOREIGN KEY(element_id) REFERENCES element(id) ON DELETE CASCADE,
 FOREIGN KEY(source_location_id) REFERENCES source_location(id) ON DELETE CASCADE);
CREATE TABLE component_access(node_id INTEGER PRIMARY KEY, type INTEGER NOT NULL,
 FOREIGN KEY(node_id) REFERENCES node(id) ON DELETE CASCADE);
CREATE TABLE element_component(id INTEGER PRIMARY KEY, element_id INTEGER, type INTEGER, data TEXT,
 FOREIGN KEY(element_id) REFERENCES element(id) ON DELETE CASCADE);
CREATE TABLE error(id INTEGER PRIMARY KEY, message TEXT, fatal INTEGER NOT NULL, indexed INTEGER NOT NULL,
 translation_unit TEXT, FOREIGN KEY(id) REFERENCES element(id) ON DELETE CASCADE);
"""


def _check_schema_constraints(database: sqlite3.Connection, tables: set[str]) -> None:
    # Column names alone also accept tables without primary or foreign keys;
    # in that case foreign_key_check cannot reveal orphan graph elements.
    with closing(sqlite3.connect(":memory:")) as reference:
        reference.executescript(SCHEMA_SQL)
        for table in tables:
            def signature(connection: sqlite3.Connection) -> tuple:
                columns = tuple((row[1], row[2].upper(), row[5]) for row in connection.execute(f"PRAGMA table_info({table})"))
                foreign_keys = sorted(tuple(row[2:]) for row in connection.execute(f"PRAGMA foreign_key_list({table})"))
                return columns, foreign_keys
            if signature(database) != signature(reference):
                raise GraphError(f"Candidate database has incompatible constraints: {table}")


def write_graph(database: Path, graph: dict, *, expected_version: int = DATABASE_VERSION) -> dict[str, int]:
    """Append a validated project graph to an app-owned candidate in one transaction.

The caller must rebuild a modern group as a whole. This function never clears an
accepted index and does not pretend that app-level publication is crash-atomic.
"""
    if expected_version != DATABASE_VERSION:
        raise GraphError(f"Unsupported database version: {expected_version}")
    validate_graph(graph)
    graph = canonical_graph(graph)
    validate_graph(graph)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=30)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables:
            db.executescript(SCHEMA_SQL)
        from script.verification.semantic_graph import SCHEMA
        expected_tables = set(SCHEMA) | {"meta"}
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != expected_tables:
            raise GraphError("Candidate database has an unknown schema")
        for table, columns in {**SCHEMA, "meta": ("id", "key", "value")}.items():
            if tuple(row[1] for row in db.execute(f"PRAGMA table_info({table})")) != columns:
                raise GraphError(f"Candidate database has incompatible columns: {table}")
        _check_schema_constraints(db, expected_tables)
        versions = db.execute("SELECT value FROM meta WHERE key='storage_version'").fetchall()
        if versions not in ([], [(str(DATABASE_VERSION),)]):
            raise GraphError(f"Candidate database has an unsupported version: {versions}")
        if not versions and db.execute("SELECT 1 FROM element LIMIT 1").fetchone():
            raise GraphError("Nonempty candidate database is missing its version")
        if db.execute("PRAGMA quick_check").fetchall() != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchall():
            raise GraphError("Candidate database failed integrity validation")
        db.execute("BEGIN IMMEDIATE")
        try:
            if not versions:
                db.execute("INSERT INTO meta(key,value) VALUES ('storage_version',?)", (str(DATABASE_VERSION),))
            nodes: dict[str, tuple[int, int]] = {}
            for identity, kind, name in db.execute("SELECT id,type,serialized_name FROM node"):
                if not _utf8_text(name) or not name or kind not in NODE_KINDS.values():
                    raise GraphError("Candidate database has an invalid node identity or kind")
                if name in nodes:
                    raise GraphError(f"Candidate database has duplicate node names: {name!r}")
                nodes[name] = identity, kind
            elements: dict[str, int] = {}

            def element() -> int:
                return db.execute("INSERT INTO element DEFAULT VALUES").lastrowid

            def node(kind: int, name: str) -> int:
                if name not in nodes:
                    identity = element()
                    db.execute("INSERT INTO node VALUES (?,?,?)", (identity, kind, name))
                    nodes[name] = identity, kind
                elif nodes[name][1] != kind:
                    raise GraphError(f"Node name collides with a different kind in the candidate: {name!r}")
                return nodes[name][0]

            for source in graph["files"]:
                path = source["path"]
                identity = node(NODE_KINDS["file"], serialized_name([path], "/"))
                elements["file:" + path] = identity
                old = db.execute("SELECT content FROM filecontent WHERE id=?", (identity,)).fetchone()
                if old is not None and old[0] != source["content"]:
                    raise GraphError(f"Conflicting source ownership/content: {path}")
                stamp = datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                language = {"python": "Python", "cpp": "C++", "rust": "Rust", "config": ""}.get(source["language"], source["language"])
                indexed, complete = source.get("indexed", True), source.get("complete", True)
                previous = db.execute("SELECT path,language,indexed,complete FROM file WHERE id=?", (identity,)).fetchone()
                if previous is not None:
                    if previous[0] != path or (previous[1] and language and previous[1] != language):
                        raise GraphError(f"Conflicting source ownership/language: {path}")
                    language = language or previous[1]
                    indexed = indexed or bool(previous[2])
                    complete = complete and bool(previous[3])
                content = source["content"]
                line_count = content.count("\n") + int(bool(content) and not content.endswith("\n"))
                db.execute("INSERT OR REPLACE INTO file VALUES (?,?,?,?,?,?,?)", (
                    identity, path, language, stamp, int(indexed), int(complete), line_count,
                ))
                db.execute("INSERT OR REPLACE INTO filecontent VALUES (?,?)", (identity, source["content"]))

            locations = {tuple(row[1:]): row[0] for row in db.execute(
                "SELECT id,file_node_id,start_line,start_column,end_line,end_column,type FROM source_location")}

            def occurrence(identity: int, value: dict) -> None:
                key = (elements["file:" + value["file"]], value["start_line"], value["start_column"],
                       value["end_line"], value["end_column"], LOCATION_KINDS[value.get("kind", "token")])
                if key not in locations:
                    locations[key] = db.execute(
                        "INSERT INTO source_location(file_node_id,start_line,start_column,end_line,end_column,type) VALUES (?,?,?,?,?,?)", key,
                    ).lastrowid
                db.execute("INSERT OR IGNORE INTO occurrence VALUES (?,?)", (identity, locations[key]))

            for symbol in graph["symbols"]:
                identity = node(NODE_KINDS[symbol["kind"]], serialized_name(symbol["name"], symbol.get("delimiter", "::")))
                elements[symbol["id"]] = identity
                definition = DEFINITIONS[symbol.get("definition", "none")]
                if definition:
                    previous = db.execute("SELECT definition_kind FROM symbol WHERE id=?", (identity,)).fetchone()
                    if (definition == DEFINITIONS["explicit"] and previous and previous[0] == definition
                            and symbol["kind"] not in ("namespace", "module", "package")):
                        prior_locations = db.execute(
                            "SELECT f.path,l.start_line,l.start_column,l.end_line,l.end_column,l.type "
                            "FROM occurrence o JOIN source_location l ON l.id=o.source_location_id "
                            "JOIN file f ON f.id=l.file_node_id WHERE o.element_id=?", (identity,),
                        ).fetchall()
                        incoming_locations = [
                            (value["file"], value["start_line"], value["start_column"], value["end_line"], value["end_column"],
                             LOCATION_KINDS[value.get("kind", "token")]) for value in symbol.get("locations", [])
                        ]
                        def definitions(locations: list) -> set:
                            scopes = {row[:5] for row in locations if row[5] == LOCATION_KINDS["scope"]}
                            return scopes or {row[:5] for row in locations if row[5] == LOCATION_KINDS["token"]}
                        prior, incoming = definitions(prior_locations), definitions(incoming_locations)
                        if prior and incoming and prior.isdisjoint(incoming):
                            raise GraphError(f"Distinct explicit definitions collide in the candidate: {symbol['name']!r}")
                    db.execute("INSERT OR REPLACE INTO symbol VALUES (?,?)", (identity, max(definition, previous[0] if previous else 0)))
                if symbol.get("access"):
                    access = {"public": 1, "protected": 2, "private": 3}[symbol["access"]]
                    db.execute("INSERT OR REPLACE INTO component_access VALUES (?,?)", (identity, access))
                for value in symbol.get("locations", []):
                    occurrence(identity, value)

            edges = {tuple(row[1:]): row[0] for row in db.execute("SELECT id,type,source_node_id,target_node_id FROM edge")}
            for reference in graph["edges"]:
                key = (EDGE_KINDS[reference["kind"]], elements[reference["source"]], elements[reference["target"]])
                if key not in edges:
                    edges[key] = element()
                    db.execute("INSERT INTO edge VALUES (?,?,?,?)", (edges[key], *key))
                for value in reference.get("locations", []):
                    occurrence(edges[key], value)
            diagnostics = {tuple(row[1:]): row[0] for row in db.execute(
                "SELECT e.id,e.message,e.fatal,e.indexed,e.translation_unit,l.file_node_id,"
                "l.start_line,l.start_column,l.end_line,l.end_column FROM error e "
                "JOIN occurrence o ON o.element_id=e.id JOIN source_location l ON l.id=o.source_location_id")}
            for diagnostic in graph["diagnostics"]:
                line, column = diagnostic.get("line", 1), diagnostic.get("column", 1)
                end_column = diagnostic.get("end_column", column)
                key = (diagnostic["message"], int(diagnostic.get("fatal", False)), 1, diagnostic["file"],
                       elements["file:" + diagnostic["file"]], line, column, line, end_column)
                if key not in diagnostics:
                    identity = element()
                    db.execute("INSERT INTO error VALUES (?,?,?,?,?)", (identity, *key[:4]))
                    diagnostics[key] = identity
                occurrence(diagnostics[key], {"file": diagnostic["file"], "start_line": line,
                           "end_line": line, "start_column": column, "end_column": end_column, "kind": "error"})
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise GraphError("Adapter output introduced a dangling database reference")
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return {key: len(graph[key]) for key in ("files", "symbols", "edges", "diagnostics")}


def graph_json(graph: dict) -> str:
    validate_graph(graph)
    return json.dumps(graph, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
