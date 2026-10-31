"""Index a Cargo workspace through rust-analyzer's semantic LSP operations.

Definitions and references come from the engine, calls from call hierarchy, and
trait implementation links from ``textDocument/implementation``. No regular
expression is used to infer a resolved Rust reference. The adapter returns the
portable graph protocol; database persistence is owned by the common writer.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import tomllib
from typing import Any
from urllib.parse import unquote, urlparse

from .rust_lsp import RustLanguageServer, RustProtocolError
from .rust_runtime import ANALYZER_VERSION, DEFAULT_DESTINATION, RUST_VERSION


class RustIndexError(RuntimeError):
    """The workspace or engine cannot produce an accepted index."""


def capabilities() -> dict:
    return {
        "id": "rust-analyzer-lsp", "protocol_version": 1, "database_version": 25,
        "language": "rust", "engine": "rust-analyzer", "engine_version": ANALYZER_VERSION,
        "compiler_version": RUST_VERSION, "editions": ["2015", "2018", "2021", "2024"],
        "coordinates": "one-based-inclusive-utf8-bytes", "coordinate_unit": "utf8-byte",
        "partial_clearing": False,
        "capabilities": ["definitions", "references", "calls", "module-dependencies",
                         "trait-impl-mapping", "macro-call-provenance", "cargo-features",
                         "cargo-target", "diagnostics", "incremental-clean-comparison"],
        "limitations": [
            "Procedural-macro expansion is not enabled; macro_rules! calls retain source provenance.",
            "Cargo configurations requiring build scripts or procedural-macro crates are rejected by this profile.",
            "Only source-mapped call hierarchy and references are recorded; generated-only symbols have no invented location.",
            "Reference edges cover definitions in the selected workspace; external calls have implicit targets without importing complete dependency source graphs.",
            "Configuration changes require a whole-group rebuild; distinct Cargo configurations have distinct symbol identities.",
        ],
    }


def _run(command: list[str], root: Path, environment: dict[str, str], timeout: float,
         *, allowed_exit_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(command, cwd=root, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="strict", start_new_session=os.name == "posix")
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.communicate()
        raise
    if process.returncode not in allowed_exit_codes:
        raise RustIndexError(f"{' '.join(command)} exited {process.returncode}:\n{stderr[-8000:]}")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _uri_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        return None
    return Path(unquote(parsed.path)).resolve()


@contextmanager
def _locked_analyzer_environment(environment: dict[str, str], cargo: str):
    """Keep the pinned engine's internal metadata calls from changing Cargo.lock.

    The 2025-03-03 engine filters cargo.extraArgs to unstable flags for metadata,
    ignoring --locked. Its toolchain resolver respects CARGO after checking the
    Cargo-home rustup proxy. Require a dedicated cache without that proxy and
    pass metadata through a quoted, temporary wrapper for the selected Cargo.
    """
    if (Path(environment["CARGO_HOME"]) / "bin/cargo").exists():
        raise RustIndexError("The Rust profile requires a Cargo dependency cache without bin/cargo; "
                             "use the prepared runtime cargo-home to guarantee locked metadata")
    executable = shutil.which(cargo, path=environment.get("PATH"))
    if not executable:
        raise RustIndexError(f"Cargo executable is missing: {cargo}")
    with tempfile.TemporaryDirectory(prefix="sourcetrail-rust-cargo-") as directory:
        wrapper = Path(directory) / "cargo"
        command = shlex.quote(str(Path(executable).resolve()))
        wrapper.write_text("#!/bin/sh\n"
                           "case \"$1\" in\n"
                           "  metadata)\n"
                           "    for argument do\n"
                           f"      [ \"$argument\" = --locked ] && exec {command} \"$@\"\n"
                           "    done\n"
                           f"    exec {command} \"$@\" --locked ;;\n"
                           f"  *) exec {command} \"$@\" ;;\n"
                           "esac\n", encoding="utf-8")
        wrapper.chmod(0o700)
        yield {**environment, "CARGO": str(wrapper)}


def _position(position: dict) -> tuple[int, int]:
    return position["line"], position["character"]


def _locations(value: Any) -> list[tuple[Path, dict]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise RustProtocolError("Invalid location list returned by rust-analyzer")
    result = []
    for item in value:
        uri = item.get("targetUri", item.get("uri", ""))
        path = _uri_path(uri)
        span = item.get("targetSelectionRange", item.get("range"))
        if path is not None and isinstance(span, dict):
            result.append((path, span))
        elif path is not None:
            raise RustProtocolError("An engine location is missing its source range")
    return result


@dataclass
class Source:
    path: Path
    content: str

    @property
    def uri(self) -> str:
        return self.path.as_uri()

    @property
    def lines(self) -> list[bytes]:
        return [line.encode("utf-8") for line in self.content.split("\n")]

    def location(self, span: dict, kind: str = "token") -> dict | None:
        """Convert negotiated UTF-8 half-open positions to inclusive DB positions."""
        start_line, start_column = _position(span["start"])
        end_line, end_column = _position(span["end"])
        lines = self.lines
        if not (0 <= start_line <= end_line < len(lines)):
            raise RustProtocolError(f"Out-of-range engine line in {self.path}")
        if start_column < 0 or start_column > len(lines[start_line]):
            raise RustProtocolError(f"Out-of-range engine start column in {self.path}")
        if end_column < 0 or end_column > len(lines[end_line]):
            raise RustProtocolError(f"Out-of-range engine end column in {self.path}")
        if (start_line, start_column) == (end_line, end_column):
            if kind == "token":
                return None
            end_column = start_column + 1
        elif (start_line, start_column) > (end_line, end_column):
            raise RustProtocolError("Reversed engine range")
        elif end_column == 0:
            # A half-open scope may finish at the following line's start. The
            # persisted inclusive endpoint is the previous visible source byte.
            end_line -= 1
            end_column = len(lines[end_line].rstrip(b"\r"))
            while end_column == 0 and end_line > start_line:
                end_line -= 1
                end_column = len(lines[end_line].rstrip(b"\r"))
            if end_column == 0:
                end_column = 1
        return {"file": str(self.path), "start_line": start_line + 1,
                "start_column": start_column + 1, "end_line": end_line + 1,
                "end_column": end_column, "kind": kind}


@dataclass
class Definition:
    source: Source
    selection: dict
    scope: dict
    identity: str
    kind: str
    names: list
    raw: dict
    synthetic_impl: bool = False

    def contains(self, position: dict) -> bool:
        return _position(self.scope["start"]) <= _position(position) < _position(self.scope["end"])


_KINDS = {
    2: "module", 3: "namespace", 4: "package", 5: "class", 6: "method",
    7: "field", 8: "field", 9: "method", 10: "enum", 11: "interface",
    12: "function", 13: "global_variable", 14: "global_variable", 22: "enum_constant",
    23: "struct", 26: "type_parameter",
}
_TYPE_KINDS = {"class", "struct", "interface", "enum", "type", "typedef", "type_parameter", "union"}
_CALLABLE_KINDS = {"function", "method"}


class WorkspaceGraph:
    def __init__(self, root: Path, metadata: dict, options: dict, server: RustLanguageServer,
                 sources: dict[Path, Source], context: dict, configuration_files: set[Path]) -> None:
        self.root = root
        self.metadata = metadata
        self.options = options
        self.server = server
        self.sources = sources
        self.context = context
        self.configuration_files = configuration_files
        self.graph: dict = {"files": [], "symbols": [], "edges": [], "diagnostics": [],
                           "context": context}
        self.definitions: list[Definition] = []
        self.symbols: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.call_locations: set[tuple] = set()
        self.active_files: set[Path] = set()
        self.package_roots = sorted(
            [(Path(package["manifest_path"]).resolve().parent, package)
             for package in metadata["packages"] if package["id"] in metadata["workspace_members"]],
            key=lambda pair: len(pair[0].parts), reverse=True,
        )
        self.target_roots = []
        for directory, package in self.package_roots:
            for target in package["targets"]:
                if self.options.get("all_targets", False) or set(target["kind"]) & {"lib", "bin", "proc-macro", "cdylib", "staticlib", "rlib", "dylib"}:
                    path = Path(target["src_path"]).resolve()
                    if path in sources:
                        self.target_roots.append((path, target, package))
                        self.active_files.add(path)

    def request_at(self, method: str, source: Source, position: dict, **extra: Any) -> Any:
        return self.server.request(method, {"textDocument": {"uri": source.uri},
                                            "position": position, **extra})

    def edge(self, source: str, target: str, kind: str, location: dict | None = None) -> None:
        if source == target and kind in ("member", "import", "override", "inheritance"):
            return
        key = source, target, kind
        edge = self.edges.setdefault(key, {"source": source, "target": target, "kind": kind,
                                            "locations": []})
        if location and location not in edge["locations"]:
            edge["locations"].append(location)

    def base_names(self, source: Source) -> list:
        for directory, package in self.package_roots:
            if not source.path.is_relative_to(directory):
                continue
            target = next((item for item in self.target_roots if item[0] == source.path), None)
            compatible = [item for item in self.target_roots if item[2]["id"] == package["id"]
                          and source.path.is_relative_to(item[0].parent)]
            if target is None and compatible:
                target = max(compatible, key=lambda item: (len(item[0].parent.parts), "lib" in item[1]["kind"]))
            crate_name = (target[1]["name"] if target else package["name"]).replace("-", "_")
            target_kind = ",".join(sorted(target[1]["kind"])) if target else "module"
            base = [{"name": crate_name, "postfix":
                     f" [package={package['name']}@{package['version']};target={target_kind};edition={package['edition']};{self.context['configuration']}]"}]
            if target and source.path != target[0]:
                relative = source.path.relative_to(target[0].parent).with_suffix("")
                parts = list(relative.parts)
                if parts[-1] == "mod":
                    parts.pop()
                base.extend(parts)
            return base
        return ["workspace", source.path.relative_to(self.root).with_suffix("").as_posix()]

    def add_definition(self, source: Source, raw: dict, parents: list, parent_id: str | None,
                       token_kinds: dict[tuple[int, int], tuple[str, bool]]) -> None:
        selection = raw["selectionRange"]
        position = selection["start"]
        resolved = _locations(self.request_at("textDocument/definition", source, position))
        synthetic_impl = raw.get("kind") == 19 and raw.get("name", "").startswith("impl ")
        if raw.get("kind") == 2 and any(not path.is_relative_to(self.root) for path, _ in resolved):
            raise RustIndexError("A Rust module resolves outside the selected workspace root")
        self_defining = any(path == source.path and _position(span["start"]) == _position(position)
                            for path, span in resolved)
        # documentSymbol is syntactic and includes #[cfg]-disabled declarations.
        # Such declarations are admitted only after semantic self-resolution.
        module_definition = raw.get("kind") == 2 and any(path in self.sources for path, _ in resolved)
        if not self_defining and not ((synthetic_impl or module_definition) and resolved):
            return
        self.active_files.add(source.path)
        if module_definition:
            self.active_files.update(path for path, _ in resolved if path in self.sources)
            for path, _ in resolved:
                if path in self.sources and path != source.path:
                    self.edge("file:" + str(source.path), "file:" + str(path), "import",
                              source.location(selection))
        semantic_kind, is_public = token_kinds.get(_position(position), ("", False))
        kind = "namespace" if synthetic_impl else _KINDS.get(raw.get("kind"), "symbol")
        if semantic_kind in ("macro", "procMacro"):
            kind = "macro"
        elif semantic_kind == "typeAlias":
            kind = "typedef"
        elif semantic_kind == "union":
            kind = "union"
        name = raw["name"]
        detail = " ".join(raw.get("detail", "").split())
        if raw.get("kind") == 13 and parent_id and self.symbols[parent_id]["kind"] in _CALLABLE_KINDS:
            kind = "symbol"
            detail += f" [local@{position['line'] + 1}:{position['character'] + 1}]"
        part = {"name": name, "postfix": f" {detail}"} if detail else name
        names = parents + [part]
        identity = "rust:" + json.dumps(names, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if identity in self.symbols and not synthetic_impl:
            raise RustIndexError(f"Colliding Rust definitions in one configuration: {names}")
        locations = [source.location(selection), source.location(raw["range"], "scope")]
        symbol = {"id": identity, "name": names, "kind": kind, "definition": "explicit",
                  "delimiter": "::", "locations": [location for location in locations if location],
                  "access": "public" if is_public else "private"}
        if identity in self.symbols:
            self.symbols[identity]["locations"].extend(location for location in symbol["locations"]
                                                       if location not in self.symbols[identity]["locations"])
        else:
            self.symbols[identity] = symbol
        definition = Definition(source, selection, raw["range"], identity, kind, names, raw, synthetic_impl)
        self.definitions.append(definition)
        if parent_id:
            self.edge(parent_id, identity, "member")
        for child in raw.get("children", []):
            self.add_definition(source, child, names, identity, token_kinds)

    def definition_at(self, path: Path, span: dict, *, impl: bool = False) -> Definition | None:
        point = _position(span["start"])
        candidates = [definition for definition in self.definitions
                      if definition.source.path == path and (impl or not definition.synthetic_impl)
                      and _position(definition.selection["start"]) <= point < _position(definition.selection["end"])]
        return min(candidates, key=lambda definition: self._extent(definition)) if candidates else None

    @staticmethod
    def _extent(definition: Definition) -> tuple[int, int]:
        start = _position(definition.scope["start"])
        end = _position(definition.scope["end"])
        return end[0] - start[0], end[1] - start[1]

    def owner(self, source: Source, span: dict) -> str:
        candidates = [definition for definition in self.definitions
                      if definition.source.path == source.path and definition.contains(span["start"])]
        if not candidates:
            return "file:" + str(source.path)
        return min(candidates, key=self._extent).identity

    def external(self, item: dict) -> str:
        path = _uri_path(item.get("uri", ""))
        detail = " ".join(item.get("detail", "").split())
        position = item.get("selectionRange", {}).get("start", {"line": 0, "character": 0})
        # Source paths disambiguate external crates not represented by the
        # selected workspace. No external source location is invented or read.
        names = [{"name": "external", "postfix":
                  f" [{path or item.get('uri', 'generated')}:{position['line'] + 1}:{position['character'] + 1}]"},
                 {"name": item.get("name", "<unknown>"), "postfix": f" {detail}" if detail else ""}]
        identity = "rust:" + json.dumps(names, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if identity not in self.symbols:
            self.symbols[identity] = {"id": identity, "name": names,
                                      "kind": _KINDS.get(item.get("kind"), "symbol"),
                                      "definition": "none", "delimiter": "::", "locations": []}
        return identity

    def collect_definitions(self) -> None:
        semantic_legend = self.server.capabilities["semanticTokensProvider"]["legend"]
        legend = semantic_legend["tokenTypes"]
        public_modifier = 1 << semantic_legend["tokenModifiers"].index("public")
        for source in self.sources.values():
            self.server.notify("textDocument/didOpen", {"textDocument": {
                "uri": source.uri, "languageId": "rust", "version": 1, "text": source.content,
            }})
            if source.path not in self.active_files:
                parents = self.request_at("experimental/parentModule", source, {"line": 0, "character": 0})
                if not _locations(parents):
                    # Files outside the selected Cargo crate graph are still
                    # observed inputs, but are not active Rust declarations.
                    continue
                self.active_files.add(source.path)
            document = {"textDocument": {"uri": source.uri}}
            raw_definitions = self.server.request("textDocument/documentSymbol", document) or []
            tokens = self.server.request("textDocument/semanticTokens/full", document) or {"data": []}
            data = tokens["data"]
            if len(data) % 5:
                raise RustProtocolError("Malformed semantic token sequence")
            token_kinds = {}
            line = column = 0
            for index in range(0, len(data), 5):
                delta_line, delta_column, length, kind, modifiers = data[index:index + 5]
                line += delta_line
                column = delta_column if delta_line else column + delta_column
                if kind >= len(legend):
                    raise RustProtocolError("Unknown semantic token kind")
                token_kinds[(line, column)] = legend[kind], bool(modifiers & public_modifier)
                if legend[kind] == "unresolvedReference":
                    self.graph["diagnostics"].append({"file": str(source.path),
                        "message": "rust-analyzer: unresolved reference", "line": line + 1,
                        "column": column + 1, "end_column": column + length, "fatal": False})
            for raw in raw_definitions:
                self.add_definition(source, raw, self.base_names(source), None, token_kinds)

    def collect_calls(self) -> None:
        for definition in list(self.definitions):
            if definition.kind not in _CALLABLE_KINDS:
                continue
            items = self.request_at("textDocument/prepareCallHierarchy", definition.source,
                                    definition.selection["start"]) or []
            for item in items:
                calls = self.server.request("callHierarchy/outgoingCalls", {"item": item}) or []
                for call in calls:
                    target_item = call["to"]
                    target_path = _uri_path(target_item["uri"])
                    target_definition = self.definition_at(target_path, target_item["selectionRange"]) if target_path else None
                    target_id = target_definition.identity if target_definition else self.external(target_item)
                    for span in call["fromRanges"]:
                        location = definition.source.location(span)
                        if location is None:
                            continue
                        self.edge(definition.identity, target_id, "call", location)
                        self.call_locations.add((str(definition.source.path), _position(span["start"]), target_id))
                        if target_path in self.sources and target_path != definition.source.path:
                            self.active_files.add(target_path)
                            self.edge("file:" + str(definition.source.path), "file:" + str(target_path), "import", location)

    def collect_references(self) -> None:
        for definition in self.definitions:
            if definition.synthetic_impl:
                continue
            references = self.request_at("textDocument/references", definition.source,
                definition.selection["start"], context={"includeDeclaration": False})
            for path, span in _locations(references):
                source = self.sources.get(path)
                if source is None:
                    continue
                self.active_files.add(path)
                if (str(path), _position(span["start"]), definition.identity) in self.call_locations:
                    continue
                kind = "macro_usage" if definition.kind == "macro" else (
                    "type_usage" if definition.kind in _TYPE_KINDS else "usage")
                location = source.location(span)
                if location is None:
                    continue
                self.edge(self.owner(source, span), definition.identity, kind, location)
                if path != definition.source.path:
                    self.edge("file:" + str(path), "file:" + str(definition.source.path), "import", location)

    def collect_implementations(self) -> None:
        for definition in self.definitions:
            if definition.kind not in {"interface", "method", "struct", "enum"}:
                continue
            locations = self.request_at("textDocument/implementation", definition.source,
                                       definition.selection["start"])
            for path, span in _locations(locations):
                implementation = self.definition_at(path, span, impl=True)
                if implementation is None:
                    continue
                location = implementation.source.location(span)
                if definition.kind == "method" and implementation.kind == "method":
                    self.edge(implementation.identity, definition.identity, "override", location)
                elif definition.kind == "interface" and implementation.synthetic_impl:
                    self.edge(implementation.identity, definition.identity, "type_usage", location)
                    concrete = _locations(self.request_at("textDocument/definition", implementation.source,
                                                           implementation.selection["start"]))
                    for concrete_path, concrete_span in concrete:
                        target = self.definition_at(concrete_path, concrete_span)
                        if target and target.kind in {"struct", "enum", "type", "typedef"}:
                            # For Rust, this edge means "implements trait". It
                            # never asserts C++-style subclass substitutability.
                            self.edge(target.identity, definition.identity, "inheritance", location)
                            self.edge(target.identity, implementation.identity, "member")
                elif definition.kind in {"struct", "enum"} and implementation.synthetic_impl:
                    self.edge(definition.identity, implementation.identity, "member")

    def finish(self, diagnostics: list[dict]) -> dict:
        self.graph["diagnostics"].extend(diagnostics)
        self.active_files.update(Path(item["file"]) for item in diagnostics if Path(item["file"]) in self.sources)
        self.graph["diagnostics"] = [item for item in self.graph["diagnostics"]
                                     if Path(item["file"]) in self.active_files]
        incomplete = {item["file"] for item in self.graph["diagnostics"] if item.get("severity", "error") == "error"}
        # A failed compilation may originate in another file, so completeness is
        # conservative over the selected Cargo configuration.
        workspace_complete = not incomplete
        self.context["inactive_inputs"] = [path.relative_to(self.root).as_posix()
                                            for path in sorted(self.sources) if path not in self.active_files]
        for path in sorted(self.sources):
            source = self.sources[path]
            self.graph["files"].append({"path": str(path), "content": source.content,
                                        "language": "rust", "indexed": True,
                                        "complete": workspace_complete, "active": path in self.active_files})
        manifests = {Path(self.metadata["workspace_root"]).resolve() / "Cargo.toml"}
        manifests.update(Path(package["manifest_path"]).resolve() for _, package in self.package_roots)
        manifests.update(self.configuration_files)
        for filename in ("Cargo.lock", "rust-toolchain", "rust-toolchain.toml", ".cargo/config", ".cargo/config.toml"):
            path = self.root / filename
            if path.is_file():
                manifests.add(path)
        for path in sorted(manifests):
            self.graph["files"].append({"path": str(path), "content": path.read_bytes().decode("utf-8"),
                                        "language": "config", "indexed": True,
                                        "complete": workspace_complete})
        included = {source["path"] for source in self.graph["files"]}
        self.graph["diagnostics"] = [item for item in self.graph["diagnostics"] if item["file"] in included]
        self.graph["symbols"] = sorted(self.symbols.values(), key=lambda item: item["id"])
        self.graph["edges"] = [self.edges[key] for key in sorted(self.edges)]
        for edge in self.graph["edges"]:
            edge["locations"].sort(key=lambda value: (value["file"], value["start_line"], value["start_column"], value["end_line"], value["end_column"]))
        self.graph["files"].sort(key=lambda item: item["path"])
        self.graph["diagnostics"].sort(key=lambda item: (item["file"], item["line"], item["column"], item["message"]))
        return self.graph


def _cargo_arguments(options: dict) -> list[str]:
    arguments = ["--locked"]
    if options.get("offline", True):
        arguments.append("--offline")
    if options.get("all_features", False):
        arguments.append("--all-features")
    elif options.get("features"):
        arguments += ["--features", ",".join(options["features"])]
    if options.get("no_default_features", False):
        arguments.append("--no-default-features")
    return arguments


def _check_diagnostics(result: subprocess.CompletedProcess[str], root: Path,
                       sources: dict[Path, Source]) -> list[dict]:
    diagnostics = []
    for line in result.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise RustIndexError("cargo check emitted a malformed JSON message") from error
        if message.get("reason") != "compiler-message":
            continue
        diagnostic = message["message"]
        if diagnostic.get("level") not in ("error", "warning", "failure-note"):
            continue
        for span in diagnostic.get("spans", []):
            if not span.get("is_primary"):
                continue
            path = (root / span["file_name"]).resolve()
            source = sources.get(path)
            if source is None:
                continue
            lines = source.content.split("\n")
            line_number = span["line_start"]
            if not 1 <= line_number <= len(lines):
                raise RustProtocolError("rustc diagnostic has an out-of-range line")
            content = lines[line_number - 1]
            scalar = span["column_start"] - 1
            if not 0 <= scalar <= len(content):
                raise RustProtocolError("rustc diagnostic has an out-of-range column")
            column = len(content[:scalar].encode("utf-8")) + 1
            width = len(content[scalar:scalar + 1].encode("utf-8")) or 1
            diagnostics.append({"file": str(path), "message": f"rustc: {diagnostic['message']}",
                                "line": line_number, "column": column,
                                "end_column": column + width - 1, "fatal": False,
                                "severity": "warning" if diagnostic["level"] == "warning" else "error"})
    if result.returncode and not any(item["severity"] == "error" for item in diagnostics):
        raise RustIndexError(f"cargo check failed without source-mapped diagnostics:\n{result.stderr[-8000:]}")
    return diagnostics


def index_project(root: Path, options: dict | None = None) -> dict:
    """Index one locked Cargo configuration, returning source-mapped semantics."""
    root = Path(root).resolve()
    options = dict(options or {})
    manifest = root / "Cargo.toml"
    if not manifest.is_file():
        raise RustIndexError(f"Cargo.toml is missing: {root}")
    if options.get("all_features") and options.get("features"):
        raise RustIndexError("Select either features or all_features")
    for name in ("all_features", "no_default_features", "all_targets", "offline", "proc_macros"):
        if name in options and not isinstance(options[name], bool):
            raise RustIndexError(f"{name} must be boolean")
    if not isinstance(options.get("features", []), list) or any(not isinstance(item, str) or not item for item in options.get("features", [])):
        raise RustIndexError("features must be a list of nonempty strings")
    if not isinstance(options.get("cfg", []), list) or any(not isinstance(item, str) or not item or "\x00" in item for item in options.get("cfg", [])):
        raise RustIndexError("cfg must be a list of nonempty strings")
    if options.get("proc_macros"):
        raise RustIndexError("This profile does not support procedural-macro expansion")
    timeout = float(options.get("timeout", 120))
    if not 0 < timeout <= 3600:
        raise RustIndexError("timeout must be between 0 and 3600 seconds")
    cargo = str(options.get("cargo") or shutil.which("cargo") or "")
    rustc = str(options.get("rustc") or shutil.which("rustc") or "")
    analyzer = Path(options.get("rust_analyzer") or os.environ.get("SOURCETRAIL_RUST_ANALYZER")
                    or DEFAULT_DESTINATION / "rust-analyzer").resolve()
    rust_src = Path(options.get("rust_src") or os.environ.get("RUST_SRC_PATH")
                    or DEFAULT_DESTINATION / "library").resolve()
    if not cargo or not rustc:
        raise RustIndexError("Rust 1.85.1 and Cargo must be available in the locked modern environment")
    if not analyzer.is_file() or not (rust_src / "core/src/lib.rs").is_file():
        raise RustIndexError("Prepare the pinned engine with python -m script.indexers.rust_runtime")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(cargo).resolve().parent) + os.pathsep + environment.get("PATH", "")
    environment["RUSTC"] = rustc
    environment["RUST_SRC_PATH"] = str(rust_src)
    environment["CARGO_HOME"] = str(Path(options.get("cargo_home") or os.environ.get("CARGO_HOME")
                                          or DEFAULT_DESTINATION / "cargo-home").resolve())
    if options.get("offline", True):
        # rust-analyzer also invokes Cargo for the sysroot. Those invocations
        # do not inherit cargo.extraArgs, so enforce the same offline policy
        # through Cargo's supported environment configuration.
        environment["CARGO_NET_OFFLINE"] = "true"
    encoded_flags = environment.get("CARGO_ENCODED_RUSTFLAGS")
    rust_flags = encoded_flags.split("\x1f") if encoded_flags is not None else shlex.split(environment.get("RUSTFLAGS", ""))
    for cfg in options.get("cfg", []):
        rust_flags.extend(("--cfg", cfg))
    if options.get("cfg"):
        environment["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(rust_flags)
    analyzer_version = _run([str(analyzer), "--version"], root, environment, timeout).stdout.strip()
    compiler_version = _run([rustc, "--version"], root, environment, timeout).stdout.strip()
    if analyzer_version != "rust-analyzer " + ANALYZER_VERSION:
        raise RustIndexError(f"Unsupported rust-analyzer version: {analyzer_version}")
    if not compiler_version.startswith("rustc " + RUST_VERSION + " "):
        raise RustIndexError(f"Unsupported Rust compiler version: {compiler_version}")
    # A source archive alone is insufficient: the analyzer obtains std/core's
    # crate graph through the standard library's locked Cargo dependencies.
    # Fail closed if that graph is unavailable, even when the user's files do
    # not happen to contain a reference exposing the missing standard library.
    standard_environment = {**environment, "RUSTC_BOOTSTRAP": "1", "CARGO_NET_OFFLINE": "true"}
    _run([cargo, "metadata", "--format-version", "1", "--locked", "--offline",
          "--manifest-path", str(rust_src / "Cargo.toml"),
          "--filter-platform", "x86_64-unknown-linux-gnu"], rust_src, standard_environment, timeout)
    cargo_args = _cargo_arguments(options)
    metadata_result = _run([cargo, "metadata", "--format-version", "1", *cargo_args],
                           root, environment, timeout)
    try:
        metadata = json.loads(metadata_result.stdout)
    except json.JSONDecodeError as error:
        raise RustIndexError("cargo metadata returned invalid JSON") from error
    if metadata.get("version") != 1 or not metadata.get("workspace_members"):
        raise RustIndexError("Unsupported or empty Cargo metadata")
    selected_packages = {node["id"] for node in metadata.get("resolve", {}).get("nodes", [])}
    for package in metadata["packages"]:
        if package["id"] not in selected_packages:
            continue
        if any(set(target["kind"]) & {"custom-build", "proc-macro"} for target in package["targets"]):
            raise RustIndexError(
                f"The selected Cargo configuration requires a build script or procedural macro ({package['name']}); "
                "this profile cannot claim complete generated-code provenance"
            )
    workspace_root = Path(metadata["workspace_root"]).resolve()
    if workspace_root != root:
        raise RustIndexError(f"Index the Cargo workspace root: {workspace_root}")
    unsupported_editions = {package["edition"] for package in metadata["packages"]} - set(capabilities()["editions"])
    if unsupported_editions:
        raise RustIndexError(f"Unsupported Rust editions: {sorted(unsupported_editions)}")
    source_paths: set[Path] = set()
    configuration_files: set[Path] = set()
    for package in metadata["packages"]:
        if package["id"] not in metadata["workspace_members"]:
            continue
        directory = Path(package["manifest_path"]).resolve().parent
        if not directory.is_relative_to(root):
            raise RustIndexError("Workspace members outside the selected root are not supported")
    excluded_directories = {".git", ".pixi", ".venv", "venv", "target", "__pycache__"}
    for current, directories, filenames in os.walk(root):
        current_path = Path(current)
        directories[:] = sorted(name for name in directories if name not in excluded_directories)
        for filename in filenames:
            path = current_path / filename
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                continue
            if filename.endswith(".rs"):
                source_paths.add(resolved)
            elif path.suffix in (".toml", ".lock"):
                configuration_files.add(resolved)
    sources = {path: Source(path, path.read_bytes().decode("utf-8")) for path in sorted(source_paths)}
    if any("\x00" in source.content for source in sources.values()):
        raise RustIndexError("Rust source contains a NUL byte")
    initial_contents = {path: hashlib.sha256(source.content.encode("utf-8")).digest() for path, source in sources.items()}
    input_manifests = {Path(package["manifest_path"]).resolve() for package in metadata["packages"]
                       if package["id"] in metadata["workspace_members"]}
    input_manifests.add(manifest)
    input_manifests.update(configuration_files)
    input_manifests.update(root / name for name in ("Cargo.lock", "rust-toolchain", "rust-toolchain.toml", ".cargo/config", ".cargo/config.toml")
                           if (root / name).is_file())
    initial_contents.update({path: hashlib.sha256(path.read_bytes()).digest() for path in input_manifests})
    # Cargo prefers the legacy filename if both files exist.
    cargo_configuration_path = root / ".cargo/config"
    if not cargo_configuration_path.is_file():
        cargo_configuration_path = root / ".cargo/config.toml"
    cargo_file_configuration = tomllib.loads(cargo_configuration_path.read_bytes().decode("utf-8")) \
        if cargo_configuration_path.is_file() else {}
    selected_target = (options.get("target") or environment.get("CARGO_BUILD_TARGET")
                       or cargo_file_configuration.get("build", {}).get("target"))
    if selected_target is not None and (not isinstance(selected_target, str) or not selected_target):
        raise RustIndexError("This Rust profile requires one target triple per configuration")
    if selected_target and (selected_target.endswith(".json") or "/" in selected_target or "\\" in selected_target):
        raise RustIndexError("Custom JSON targets are not observed by this Rust profile; select a target triple")
    config_data = {"features": sorted(set(options.get("features", []))),
                   "all_features": bool(options.get("all_features", False)),
                   "no_default_features": bool(options.get("no_default_features", False)),
                   "target": selected_target or "host",
                   "all_targets": bool(options.get("all_targets", False)),
                   "cfg": sorted(set(options.get("cfg", []))), "rust_flags": rust_flags,
                   "cargo_configuration_sha256": hashlib.sha256(cargo_configuration_path.read_bytes()).hexdigest()
                       if cargo_configuration_path.is_file() else None}
    configuration_key = hashlib.sha256(json.dumps(config_data, sort_keys=True).encode()).hexdigest()[:16]
    context = {"engine": analyzer_version, "compiler": compiler_version,
               "configuration": "cfg=" + configuration_key, **config_data}
    cargo_configuration = {
        "sysrootSrc": str(rust_src), "features": "all" if config_data["all_features"] else config_data["features"],
        "noDefaultFeatures": config_data["no_default_features"], "allTargets": config_data["all_targets"],
        "buildScripts": {"enable": False}, "extraArgs": cargo_args,
        # The engine default additionally enables cfg(miri). Do not index a
        # different configuration than the compiler invocation we validated.
        "cfgs": config_data["cfg"],
    }
    if selected_target:
        cargo_configuration["target"] = selected_target
    configuration = {"cargo": cargo_configuration, "checkOnSave": False,
                     "diagnostics": {"enable": False}, "procMacro": {"enable": False},
                     "cachePriming": {"enable": False}, "numThreads": 2,
                     "cfg": {"setTest": config_data["all_targets"]}}
    check_args = [cargo, "check", "--workspace", "--message-format=json", *cargo_args]
    if selected_target:
        check_args += ["--target", selected_target]
    if config_data["all_targets"]:
        check_args.append("--all-targets")
    check_result = _run(check_args, root, environment, timeout, allowed_exit_codes=(0, 101))
    diagnostics = _check_diagnostics(check_result, root, sources)
    with _locked_analyzer_environment(environment, cargo) as analyzer_environment:
        with RustLanguageServer(analyzer, root, analyzer_environment, configuration, timeout) as server:
            builder = WorkspaceGraph(root, metadata, options, server, sources, context, configuration_files)
            builder.collect_definitions()
            builder.collect_calls()
            builder.collect_references()
            builder.collect_implementations()
            graph = builder.finish(diagnostics)
    for path, expected in initial_contents.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != expected:
            raise RustIndexError(f"Rust source changed during indexing: {path}")
    return graph
