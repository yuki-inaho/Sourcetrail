#!/usr/bin/env python3
"""Compare completed schema-25 indexes by an explicit semantic observation profile.

Numeric row IDs, row order and modification timestamps are not observations.
Full names/signatures, edge direction, occurrences, diagnostics, ambiguity and
file completeness are. This is graph equivalence for identical input/configuration,
not equivalence of the indexed programs or all GUI behaviour (GRAPH-001).
"""

from __future__ import annotations

import argparse
from contextlib import closing
import difflib
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any


PROFILE = "schema25-exact-v1"
ROOT_TOKEN = "${PROJECT_ROOT}"
SCHEMA = {
    "element": ("id",),
    "node": ("id", "type", "serialized_name"),
    "symbol": ("id", "definition_kind"),
    "edge": ("id", "type", "source_node_id", "target_node_id"),
    "file": ("id", "path", "language", "modification_time", "indexed", "complete", "line_count"),
    "filecontent": ("id", "content"),
    "local_symbol": ("id", "name"),
    "source_location": ("id", "file_node_id", "start_line", "start_column", "end_line", "end_column", "type"),
    "occurrence": ("element_id", "source_location_id"),
    "component_access": ("node_id", "type"),
    "element_component": ("id", "element_id", "type", "data"),
    "error": ("id", "message", "fatal", "indexed", "translation_unit"),
}


class SnapshotError(ValueError):
    """The database cannot be interpreted safely by this observation profile."""


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def ordered(values: Any) -> list[Any]:
    # Keep multiplicity: changing a duplicate into a single fact is observable.
    return sorted(values, key=stable_json)


class Normalizer:
    def __init__(self, project_root: Path):
        self.root = project_root.resolve().as_posix().rstrip("/")
        if not self.root:
            raise SnapshotError("The project root must not be the filesystem root")
        self.prefix = re.compile(r"(?<![\w./-])" + re.escape(self.root) + r"(?=/|$)")

    def text(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise SnapshotError(f"Expected text, found {type(value).__name__}")
        if ROOT_TOKEN in value:
            raise SnapshotError(f"Input contains reserved normalization token {ROOT_TOKEN}")
        return self.prefix.sub(lambda _: ROOT_TOKEN, value)

    def name(self, value: str) -> list[Any]:
        # NAME-001: do not drop signature prefix/postfix (C++ overload identity).
        if not isinstance(value, str):
            raise SnapshotError("A node has no serialized name")
        delimiter, meta, hierarchy = value.partition("\tm")
        if not meta or not hierarchy:
            raise SnapshotError(f"Malformed serialized name: {value!r}")
        parts = []
        for part in hierarchy.split("\tn"):
            name, sep, signature = part.partition("\ts")
            prefix, sig_sep, postfix = signature.partition("\tp")
            if not sep or not sig_sep:
                raise SnapshotError(f"Malformed name part: {part!r}")
            # CxxAstVisitorComponentIndexer disambiguates main by its file path.
            # Preserve that per-file identity while relocating the known suffix.
            main_prefix = ".:main:."
            normalized_name = (
                main_prefix + self.text(name[len(main_prefix):])
                if name.startswith(main_prefix) else self.text(name)
            )
            parts.append([normalized_name, self.text(prefix), self.text(postfix)])
        return [delimiter, parts]


def read_snapshot(database: Path, project_root: Path) -> dict[str, Any]:
    """Read an existing DB in a single read transaction; fail closed on drift."""
    if not database.is_file():
        raise SnapshotError(f"Index database does not exist: {database}")
    normal = Normalizer(project_root)
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise SnapshotError("SQLite integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise SnapshotError("SQLite foreign-key check failed")
            version = db.execute("SELECT value FROM meta WHERE key = 'storage_version'").fetchall()
            if version != [("25",)]:
                raise SnapshotError(f"Unsupported schema version: {version!r}")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            unexpected = tables - set(SCHEMA) - {"meta", "sqlite_sequence"}
            if unexpected:
                raise SnapshotError(f"Unmodelled database tables: {sorted(unexpected)}")
            rows: dict[str, list[tuple[Any, ...]]] = {}
            for table, columns in SCHEMA.items():
                actual = tuple(row[1] for row in db.execute(f"PRAGMA table_info({table})"))
                if actual != columns:
                    raise SnapshotError(f"Unmodelled schema for {table}: {actual!r}")
                rows[table] = db.execute(f"SELECT * FROM {table}").fetchall()
                if columns[0] == "id":
                    identifiers = [row[0] for row in rows[table]]
                    if any(not isinstance(value, int) or value <= 0 for value in identifiers):
                        raise SnapshotError(f"Invalid numeric identity in {table}")
                    if len(set(identifiers)) != len(identifiers):
                        raise SnapshotError(f"Duplicate numeric identity in {table}")
    except sqlite3.Error as error:
        raise SnapshotError(f"Cannot read schema-25 index: {error}") from error

    nodes = {row[0]: ["node", row[1], normal.name(row[2])] for row in rows["node"]}
    files = {row[0]: row for row in rows["file"]}

    def reference(mapping: dict[int, Any], identifier: int, label: str) -> Any:
        if identifier not in mapping:
            raise SnapshotError(f"Dangling {label} reference: {identifier}")
        return mapping[identifier]

    locations = {}
    for identifier, file_id, *position in rows["source_location"]:
        reference(files, file_id, "file")
        locations[identifier] = [reference(nodes, file_id, "node"), *position]

    by_element: dict[int, list[Any]] = {}
    for element_id, location_id in rows["occurrence"]:
        by_element.setdefault(element_id, []).append(reference(locations, location_id, "location"))

    edges = {
        identifier: ["edge", kind, reference(nodes, source, "source node"), reference(nodes, target, "target node")]
        for identifier, kind, source, target in rows["edge"]
    }
    local_symbols = {
        identifier: ["local", normal.text(name), ordered(by_element.get(identifier, []))]
        for identifier, name in rows["local_symbol"]
    }
    errors = {
        identifier: ["error", normal.text(message), fatal, indexed, normal.text(unit),
                     ordered(by_element.get(identifier, []))]
        for identifier, message, fatal, indexed, unit in rows["error"]
    }
    elements: dict[int, Any] = {}
    for kind, mapping in (("node", nodes), ("edge", edges), ("local", local_symbols), ("error", errors)):
        seen = set()
        for identifier, key in mapping.items():
            encoded = stable_json(key)
            if encoded in seen:
                raise SnapshotError(f"Ambiguous duplicate {kind} identity; profile needs explicit disambiguation")
            if identifier in elements:
                raise SnapshotError(f"Element belongs to multiple kinds: {identifier}")
            seen.add(encoded)
            elements[identifier] = key
    stored_elements = {identifier for (identifier,) in rows["element"]}
    if not set(elements).issubset(stored_elements):
        raise SnapshotError("Typed elements are missing from the element table")
    # addSourceLocations allocates base element rows but uses a separate location
    # ID sequence. Unreferenced allocator rows carry no graph observation. Any
    # occurrence/component pointing at an untyped row is still rejected below.

    content = []
    for identifier, value in rows["filecontent"]:
        reference(files, identifier, "content file")
        if not isinstance(value, (str, bytes)):
            raise SnapshotError("File content is neither text nor bytes")
        encoded = value.encode("utf-8") if isinstance(value, str) else value
        # Do not replace roots in source contents: they can be program literals.
        content.append([reference(nodes, identifier, "content node"), hashlib.sha256(encoded).hexdigest()])

    return {
        "profile": PROFILE,
        "storage_version": 25,
        "nodes": ordered(nodes.values()),
        "symbols": ordered([reference(nodes, identifier, "symbol node"), kind]
                           for identifier, kind in rows["symbol"]),
        "edges": ordered(edges.values()),
        "files": ordered([reference(nodes, row[0], "file node"), normal.text(row[1]), row[2], *row[4:]]
                         for row in rows["file"]),
        "file_contents": ordered(content),
        "local_symbols": ordered(local_symbols.values()),
        "locations": ordered(locations.values()),
        "occurrences": ordered([reference(elements, element, "occurrence element"),
                                reference(locations, location, "occurrence location")]
                               for element, location in rows["occurrence"]),
        "access": ordered([reference(nodes, identifier, "access node"), kind]
                          for identifier, kind in rows["component_access"]),
        "components": ordered([reference(elements, element, "component element"), kind, normal.text(data)]
                              for _, element, kind, data in rows["element_component"]),
        "errors": ordered(errors.values()),
    }


def snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> str:
    def lines(snapshot: dict[str, Any]) -> list[str]:
        return (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n").splitlines(True)
    return "".join(difflib.unified_diff(lines(before), lines(after), fromfile="before", tofile="after"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export", help="Export a deterministic semantic snapshot")
    export.add_argument("database", type=Path)
    export.add_argument("--root", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    compare = subparsers.add_parser("compare", help="Compare two completed databases (0=equal, 1=different, 2=invalid)")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--before-root", required=True, type=Path)
    compare.add_argument("--after-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            if args.output.resolve() == args.database.resolve() or (
                args.output.exists() and args.database.exists() and args.output.samefile(args.database)
            ):
                raise SnapshotError("Snapshot output must not overwrite the input database")
            snapshot = read_snapshot(args.database, args.root)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print(f"Exported {PROFILE}: {args.output}")
            return 0
        before = read_snapshot(args.before, args.before_root)
        after = read_snapshot(args.after, args.after_root)
        difference = snapshot_diff(before, after)
        if difference:
            print(difference, end="")
            return 1
        print(f"Equivalent under {PROFILE}")
        return 0
    except (SnapshotError, OSError) as error:
        print(f"Cannot compare: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
