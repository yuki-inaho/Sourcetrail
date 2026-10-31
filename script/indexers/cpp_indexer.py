"""Clang 18 C/C++ adapter for the versioned, language-neutral indexing graph.

The stable libclang *indexing* API is intentional: a cursor-only AST walk loses
declarations inside C++20 ``export`` wrappers.  No compilation database command
is executed.  Only its compiler arguments are passed to libclang.
"""

from __future__ import annotations

import bisect
import ctypes
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".c++", ".C", ".cppm", ".ixx", ".mpp"}
HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".inc", ".inl"}
OBSERVATION_EXCLUDES = {".git", ".pixi", ".venv", "venv", "target", "__pycache__"}
IGNORED_DIRECTORIES = OBSERVATION_EXCLUDES | {"build", "node_modules"}
SUPPORTED_ENGINE_VERSIONS = {"18.1.1", "18.1.8"}


def _clang():
    try:
        from clang import cindex
    except ImportError as exc:
        raise RuntimeError("The modern C++ adapter requires the locked libclang package") from exc
    if not cindex.Config.loaded:
        # A conda C library and compiler of the same patch version can share
        # module BMI files.  The wheel's bundled C library is the fallback.
        candidates = [*(Path(sys.prefix) / "lib").glob("libclang.so.18*"),
                      Path(sys.prefix) / "lib" / "libclang.so.13"]
        library = next((p for p in candidates if p.is_file()), None)
        if library is not None:
            cindex.Config.set_library_file(str(library))
    lib = cindex.conf.lib
    lib.clang_getClangVersion.restype = cindex._CXString
    lib.clang_getClangVersion.errcheck = cindex._CXString.from_result
    lib.clang_File_tryGetRealPathName.argtypes = [cindex.File]
    lib.clang_File_tryGetRealPathName.restype = cindex._CXString
    lib.clang_File_tryGetRealPathName.errcheck = cindex._CXString.from_result
    version_text = lib.clang_getClangVersion()
    match = re.search(r"clang version (\d+\.\d+\.\d+)", version_text)
    if not match or match.group(1) not in SUPPORTED_ENGINE_VERSIONS:
        raise RuntimeError(f"Unsupported modern C++ engine: {version_text}")
    return cindex, match.group(1)


def capabilities() -> dict[str, Any]:
    _, version = _clang()
    return {
        "adapter": "cxx-modern",
        "protocol_version": 1,
        "database_version": 25,
        "engine": "libclang",
        "engine_version": version,
        "language": "cpp",
        "standards": ["c++17", "c++20", "c++23"],
        "coordinate_system": "utf8-bytes-1-based-inclusive",
        "coordinate_unit": "utf8-byte",
        "partial_clearing": False,
        "capabilities": [
            "definitions", "references", "calls", "overloads", "inheritance",
            "include-dependencies", "compilation-database", "concepts",
            "coroutines", "module-interfaces", "prebuilt-module-imports",
            "diagnostics", "macro-provenance",
        ],
        "limitations": [
            "Prebuilt modules require a BMI produced by the same Clang patch version.",
            "Implicit compiler-generated references are omitted; user source positions are retained.",
            "Multiple different build configurations for one translation unit must be selected separately.",
            "Only project-owned declarations are indexed; external symbols remain reference targets.",
            "Unselected source/header inputs are observed for refresh and explicitly diagnosed without semantic declarations.",
        ],
    }


def _path(root: Path, value: str | Path, directory: Path | None = None) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else ((directory or root) / path).resolve()


def _is_owned(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)


def _discover_sources(root: Path) -> set[Path]:
    sources: set[Path] = set()
    for directory, children, files in os.walk(root):
        children[:] = sorted(child for child in children if child not in IGNORED_DIRECTORIES)
        for name in files:
            path = Path(directory) / name
            if path.suffix in SOURCE_SUFFIXES:
                sources.add(path.resolve())
    return sources


def _discover_observed_inputs(root: Path) -> set[Path]:
    """Match native enumeration even when a CDB selects only some files."""
    sources: set[Path] = set()
    for directory, children, files in os.walk(root):
        children[:] = sorted(child for child in children if child not in OBSERVATION_EXCLUDES)
        for name in files:
            path = Path(directory) / name
            if path.suffix in SOURCE_SUFFIXES | HEADER_SUFFIXES:
                path = path.resolve()
                if not _is_owned(path, root):
                    raise ValueError(f"C++ source symlink leaves the selected root: {path}")
                sources.add(path)
    return sources


def _expand_response_arguments(arguments: list[str], directory: Path, active: frozenset[Path] = frozenset(), inputs: set[Path] | None = None) -> list[str]:
    result: list[str] = []
    for arg in arguments:
        if not arg.startswith("@"):
            result.append(arg)
            continue
        response = _path(directory, arg[1:])
        if response in active or len(active) >= 16:
            raise ValueError(f"Cyclic or excessive compiler response files: {response}")
        if inputs is not None:
            inputs.add(response)
        result.extend(_expand_response_arguments(
            shlex.split(response.read_text(encoding="utf-8")), directory, active | {response}, inputs
        ))
    return result


def _compiler_arguments(arguments: list[str], source: Path, directory: Path, inputs: set[Path] | None = None) -> list[str]:
    """Remove output actions while preserving the compilation's meaning and cwd."""
    arguments = _expand_response_arguments(arguments, directory, inputs=inputs)
    if not arguments:
        raise ValueError("Empty compilation database command")
    # CCache/sccache are transparent compiler launchers, not shell programs.
    first = 2 if Path(arguments[0]).name in {"ccache", "sccache"} else 1
    if first == 2 and len(arguments) < 2:
        raise ValueError("Compilation database launcher has no compiler")
    result = ["-working-directory", str(directory)]
    skip_next = False
    consumes_output = {"-o", "-MF", "-MT", "-MQ", "-MJ", "--serialize-diagnostics"}
    output_actions = {"-c", "-S", "-E", "-M", "-MM", "-MD", "-MMD", "-MP", "-MG", "--precompile", "-fsyntax-only"}
    for arg in arguments[first:]:
        if skip_next:
            skip_next = False
            continue
        if arg in consumes_output:
            skip_next = True
            continue
        if arg in output_actions or any(arg.startswith(p) and arg != p for p in consumes_output if p != "-o"):
            continue
        if arg in {"-load", "-plugin", "-add-plugin"} or arg.startswith(("-fplugin", "-load=")):
            raise ValueError("Compiler plugins are outside the modern C++ indexing contract")
        if not arg.startswith("-") and _path(directory, arg) == source:
            continue
        result.append(arg)
    if skip_next:
        raise ValueError("Compiler output option has no argument")
    return result


def _commands(root: Path, options: dict[str, Any], inputs: set[Path] | None = None,
              response_inputs: set[Path] | None = None) -> list[tuple[Path, list[str]]]:
    database = options.get("compilation_database")
    if database is not None and not isinstance(database, (str, Path)):
        raise ValueError("compilation_database must be a path")
    if database is None and (root / "compile_commands.json").is_file():
        database = root / "compile_commands.json"
    extra = options.get("arguments", [])
    if not isinstance(extra, list) or any(not isinstance(x, str) for x in extra):
        raise ValueError("C++ arguments must be a list of strings")
    responses: set[Path] = set()
    extra = _expand_response_arguments(extra, root, inputs=responses)
    files = options.get("files", [])
    if not isinstance(files, list) or any(not isinstance(p, str) for p in files):
        raise ValueError("C++ files must be a list of paths")
    selected = {_path(root, p) for p in files}
    commands: dict[Path, list[str]] = {}
    if database is not None:
        database_path = _path(root, database)
        if database_path.is_dir():
            database_path /= "compile_commands.json"
        if inputs is not None:
            inputs.add(database_path)
        entries = json.loads(database_path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("Compilation database must be an array")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
                raise ValueError("Invalid compilation database entry")
            directory = _path(root, entry.get("directory", str(database_path.parent)), database_path.parent)
            source = _path(root, entry["file"], directory)
            if not _is_owned(source, root) or (selected and source not in selected):
                continue
            argv = entry.get("arguments")
            if argv is None:
                if not isinstance(entry.get("command"), str):
                    raise ValueError("Compilation database entry has no command or arguments")
                argv = shlex.split(entry["command"])
            if not isinstance(argv, list) or any(not isinstance(x, str) for x in argv):
                raise ValueError("Invalid compilation database arguments")
            args = _compiler_arguments(argv, source, directory, responses) + extra
            if source in commands and commands[source] != args:
                raise ValueError(f"Ambiguous compilation configurations for {source}")
            commands[source] = args
    else:
        sources = selected or _discover_sources(root)
        for source in sources:
            if not _is_owned(source, root):
                raise ValueError(f"Translation unit outside the project: {source}")
            standard = options.get("standard", "c++23")
            if not isinstance(standard, str) or standard not in {"c++11", "c++14", "c++17", "c++20", "c++23", "gnu++11", "gnu++14", "gnu++17", "gnu++20", "gnu++23", "c11", "c17", "c23"}:
                raise ValueError(f"Unsupported language standard: {standard}")
            language = "c" if source.suffix == ".c" and standard.startswith("c") and not standard.startswith("c++") else "c++"
            commands[source] = ["-working-directory", str(root), "-x", language, f"-std={standard}", *extra]
    if inputs is not None:
        inputs.update(responses)
    if response_inputs is not None:
        response_inputs.update(responses)
    if not commands:
        if database is not None and entries == [] and not _discover_sources(root) and not selected:
            return []  # Explicit empty build graph after the last source deletion.
        if not (database is None and options.get("allow_empty") is True and not selected):
            raise ValueError("No C/C++ translation units selected")
    if selected - commands.keys():
        raise ValueError("Selected C/C++ files are missing from the compilation database")
    resource_dir = options.get("resource_dir")
    if resource_dir is None:
        candidate = Path(sys.prefix) / "lib" / "clang" / "18"
        if (candidate / "include").is_dir():
            resource_dir = str(candidate)
    for args in commands.values():
        if any(arg in {"-load", "-plugin", "-add-plugin"} or arg.startswith(("-fplugin", "-load=")) for arg in args):
            raise ValueError("Compiler plugins are outside the modern C++ indexing contract")
        if resource_dir and not any(a.startswith("-resource-dir") for a in args):
            args.extend(["-resource-dir", str(_path(root, resource_dir))])
    return sorted(commands.items())


class _Source:
    def __init__(self, path: Path):
        self.path = path
        self.raw = path.read_bytes()
        self.text = self.raw.decode("utf-8")
        if b"\0" in self.raw:
            raise ValueError(f"NUL in C++ source: {path}")
        self.starts = [0, *(match.end() for match in re.finditer(b"\n", self.raw))]

    def point(self, offset: int) -> tuple[int, int]:
        if not 0 <= offset < len(self.raw):
            raise ValueError(f"Clang returned an out-of-range offset for {self.path}")
        line = bisect.bisect_right(self.starts, offset)
        return line, offset - self.starts[line - 1] + 1

    def span(self, start: int, end: int, kind: str = "token") -> dict[str, Any] | None:
        if not self.raw or end <= start or start < 0 or end > len(self.raw):
            return None
        # A scope can end after a line terminator; retain only source bytes.
        while end > start and self.raw[end - 1] in b"\r\n":
            end -= 1
        if end <= start:
            return None
        a, b = self.point(start), self.point(end - 1)
        return {"file": str(self.path), "start_line": a[0], "start_column": a[1],
                "end_line": b[0], "end_column": b[1], "kind": kind}


class _Graph:
    def __init__(self, root: Path, cindex):
        self.root = root
        self.c = cindex
        self.sources: dict[Path, _Source] = {}
        self.files: dict[Path, dict[str, Any]] = {}
        self.symbols: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.diagnostics: list[dict[str, Any]] = []
        self.modules: dict[Path, str] = {}
        self.translation_unit = None
        self._ensuring: set[str] = set()

    def source(self, path: Path) -> _Source:
        path = path.resolve()
        if path not in self.sources:
            self.sources[path] = _Source(path)
            self.files[path] = {"path": str(path), "content": self.sources[path].text,
                                "language": "cpp", "indexed": _is_owned(path, self.root), "complete": True}
        return self.sources[path]

    @staticmethod
    def add_location(target: dict[str, Any], location: dict[str, Any] | None) -> None:
        if location is not None and location not in target["locations"]:
            target["locations"].append(location)

    def edge(self, source: str | None, target: str | None, kind: str, location=None) -> None:
        if not source or not target or (source == target and kind != "call"):
            return
        edge = self.edges.setdefault((source, target, kind), {
            "source": source, "target": target, "kind": kind, "locations": [],
        })
        self.add_location(edge, location)

    def cursor_path(self, cursor) -> Path | None:
        return self.file_path(cursor.location.file) if cursor.location.file else None

    def file_path(self, file) -> Path:
        # Header names may be relative to a compilation database directory,
        # which is intentionally different from this Python process's cwd.
        name = self.c.conf.lib.clang_File_tryGetRealPathName(file) or file.name
        return _path(self.root, name)

    def token_location(self, cursor, location=None) -> dict[str, Any] | None:
        location = location or cursor.location
        if not location.file:
            return None
        path = self.file_path(location.file)
        if not _is_owned(path, self.root) or not path.is_file():
            return None
        source = self.source(path)
        start = location.offset
        # Clang's token extent gives a spelling's byte length, including Unicode.
        for token in cursor.get_tokens():
            if token.location.file and self.file_path(token.location.file) == path and token.location.offset == start:
                return source.span(start, token.extent.end.offset)
        match = re.match(rb"(?:[^\W\d]|[^\x00-\x7f])(?:\w|[^\x00-\x7f])*", source.raw[start:])
        return source.span(start, start + (len(match.group()) if match else 1))

    def scope_location(self, cursor) -> dict[str, Any] | None:
        start, end = cursor.extent.start, cursor.extent.end
        if not start.file or not end.file or self.file_path(start.file) != self.file_path(end.file):
            return None
        path = self.file_path(start.file)
        if not _is_owned(path, self.root):
            return None
        return self.source(path).span(start.offset, end.offset, "scope")

    def _kind(self, cursor) -> str:
        name = cursor.kind.name
        return {
            "NAMESPACE": "namespace", "NAMESPACE_ALIAS": "namespace",
            "STRUCT_DECL": "struct", "CLASS_DECL": "class", "UNION_DECL": "union",
            "CLASS_TEMPLATE": "class", "CLASS_TEMPLATE_PARTIAL_SPECIALIZATION": "class",
            "ENUM_DECL": "enum", "ENUM_CONSTANT_DECL": "enum_constant",
            "TYPEDEF_DECL": "typedef", "TYPE_ALIAS_DECL": "typedef", "CONCEPT_DECL": "type",
            "FUNCTION_DECL": "function", "FUNCTION_TEMPLATE": "function",
            "CXX_METHOD": "method", "CONSTRUCTOR": "method", "DESTRUCTOR": "method",
            "CONVERSION_FUNCTION": "method", "FIELD_DECL": "field",
            "PARM_DECL": "symbol", "TEMPLATE_TYPE_PARAMETER": "type_parameter",
            "TEMPLATE_NON_TYPE_PARAMETER": "type_parameter", "TEMPLATE_TEMPLATE_PARAMETER": "type_parameter",
            "MACRO_DEFINITION": "macro", "VAR_DECL": "global_variable",
        }.get(name, "symbol")

    def _parent(self, cursor):
        parent = cursor.semantic_parent
        seen = set()
        while parent and parent.kind.name not in {"TRANSLATION_UNIT", "NO_DECL_FOUND", "INVALID_FILE"}:
            if parent.hash in seen:
                break
            seen.add(parent.hash)
            if (parent.spelling or parent.kind.name == "NAMESPACE") and parent.kind.name != "UNEXPOSED_DECL":
                return parent
            parent = parent.semantic_parent
        return None

    def _name_part(self, cursor) -> dict[str, str]:
        if cursor.kind.name == "FUNCTION_TEMPLATE":
            cursor = cursor.canonical
        part = {"name": cursor.spelling or "<anonymous>", "prefix": "", "postfix": ""}
        if self._kind(cursor) in {"function", "method"}:
            part["prefix"] = cursor.result_type.spelling
            parameters = [a.type.spelling for a in cursor.get_arguments()]
            if cursor.kind.name == "FUNCTION_TEMPLATE" and not parameters:
                parameters = [a.type.spelling for a in cursor.get_children() if a.kind.name == "PARM_DECL"]
            try:
                if cursor.type.is_function_variadic():
                    parameters.append("...")
            except Exception:
                pass  # Non-function dependent template types have no variadic query.
            part["postfix"] = "(" + ", ".join(parameters) + ")"
            spelling = cursor.type.spelling
            suffix = re.search(r"\)\s*((?:const|volatile|noexcept|&&|&)(?:[\s\w&()]*))$", spelling)
            if suffix:
                part["postfix"] += " " + suffix.group(1)
            if cursor.storage_class.name == "STATIC":
                part["prefix"] = "static " + part["prefix"]
            if cursor.kind.name == "FUNCTION_TEMPLATE" or self._explicit_specialization(cursor):
                canonical = cursor.canonical
                bodies = [child.extent.start.offset for child in canonical.get_children()
                          if child.kind.name == "COMPOUND_STMT"]
                body_start = min(bodies) if bodies else canonical.extent.end.offset
                header = [token.spelling for token in canonical.get_tokens()
                          if token.extent.start.offset < body_start and token.spelling != ";"
                          and token.kind != self.c.TokenKind.COMMENT]
                # Clang 18 USRs omit associated constraints. Keeping the full
                # canonical template declaration prevents two constrained
                # overloads from silently becoming one storage symbol.
                part["postfix"] += " [" + " ".join(header) + "]"
        elif self._kind(cursor) in {"global_variable", "field"}:
            part["prefix"] = cursor.type.spelling
        return part

    @staticmethod
    def _explicit_specialization(cursor) -> bool:
        tokens = iter(cursor.get_tokens())
        return [token.spelling for _, token in zip(range(3), tokens)] == ["template", "<", ">"]

    def symbol(self, cursor, definition: str | None = None, declared: bool = False) -> str | None:
        if not cursor or cursor.kind.name in {"TRANSLATION_UNIT", "NO_DECL_FOUND", "INVALID_FILE", "UNEXPOSED_DECL"}:
            return None
        if cursor.kind.name in {"FUNCTION_DECL", "CXX_METHOD"} and not self._explicit_specialization(cursor):
            template = self.c.conf.lib.clang_getSpecializedCursorTemplate(cursor)
            if template is None and cursor.get_usr().startswith("c:@FT@"):
                at_location = self.c.Cursor.from_location(cursor.translation_unit, cursor.location)
                template = (at_location if at_location.kind.name == "FUNCTION_TEMPLATE"
                            else self.c.conf.lib.clang_getSpecializedCursorTemplate(at_location))
            if template is not None and template.kind.name == "FUNCTION_TEMPLATE":
                cursor = template
        usr = cursor.get_usr()
        if not usr or usr == "c:":
            return None
        path = self.cursor_path(cursor)
        local = path is not None and (not usr.startswith("c:@") or cursor.linkage.name == "INTERNAL"
                                      or not cursor.spelling)
        owner = self.modules.get(path, "")
        identity = "cxx:" + (owner + ":" if owner else "") + usr
        if cursor.kind.name == "FUNCTION_TEMPLATE":
            # The canonical declaration is shared by redeclarations, whereas
            # distinct constrained overloads can have the same Clang 18 USR.
            canonical = cursor.canonical
            canonical_path = self.cursor_path(canonical)
            if canonical_path is not None:
                relative = canonical_path.relative_to(self.root).as_posix() if _is_owned(canonical_path, self.root) else str(canonical_path)
                identity += f":template:{relative}:{canonical.location.offset}"
        if local:
            identity += ":" + (path.relative_to(self.root).as_posix() if _is_owned(path, self.root) else str(path))
            if self._kind(cursor) == "symbol":
                identity += f":{cursor.location.offset}"
        if identity in self._ensuring:
            return identity
        self._ensuring.add(identity)
        try:
            parent = self._parent(cursor)
            parent_id = self.symbol(parent) if parent is not None else None
            names = list(self.symbols[parent_id]["name"]) if parent_id in self.symbols else []
            if not names and owner:
                names.append({"name": owner, "prefix": "", "postfix": ""})
            part = self._name_part(cursor)
            # Function-local and internal-linkage entities can share a spelling
            # but not a storage name. Keep the discriminator out of their USR.
            if local and path is not None:
                relative = path.relative_to(self.root).as_posix() if _is_owned(path, self.root) else str(path)
                if self._kind(cursor) in {"function", "global_variable"}:
                    part["postfix"] += f" ({relative})"
                elif self._kind(cursor) == "symbol" or not cursor.spelling:
                    part["postfix"] += f" @{relative}:{cursor.location.line}:{cursor.location.column}"
            names.append(part)
            symbol = self.symbols.setdefault(identity, {
                "id": identity, "name": names, "kind": self._kind(cursor),
                "definition": "none", "delimiter": "::", "locations": [],
            })
            access = cursor.access_specifier.name.lower()
            if access in {"public", "protected", "private"}:
                symbol["access"] = access
            if definition == "explicit" or (definition == "implicit" and symbol["definition"] == "none"):
                symbol["definition"] = definition
            if declared and path is not None and _is_owned(path, self.root):
                self.add_location(symbol, self.token_location(cursor))
                if definition == "explicit":
                    self.add_location(symbol, self.scope_location(cursor))
            if parent_id:
                self.edge(parent_id, identity, "member")
            elif owner:
                self.edge("cxx:module:" + owner, identity, "member")
            if self._explicit_specialization(cursor):
                template = self.c.conf.lib.clang_getSpecializedCursorTemplate(cursor)
                if template is not None:
                    self.edge(identity, self.symbol(template), "template_specialization")
            return identity
        finally:
            self._ensuring.remove(identity)

    def record_diagnostics(self, tu, main: Path) -> None:
        for diagnostic in tu.diagnostics:
            if diagnostic.severity < self.c.Diagnostic.Warning:
                continue
            location = diagnostic.location
            path = self.file_path(location.file) if location.file else main
            if not path.is_file():
                path = main
            source = self.source(path)
            severity = "fatal" if diagnostic.severity >= self.c.Diagnostic.Fatal else "error" if diagnostic.severity >= self.c.Diagnostic.Error else "warning"
            if diagnostic.severity >= self.c.Diagnostic.Error:
                self.files[path]["complete"] = False
                self.files[main]["complete"] = False
            offset = min(max(location.offset, 0), len(source.raw))
            while 0 < offset < len(source.raw) and source.raw[offset] & 0xC0 == 0x80:
                offset -= 1
            row = bisect.bisect_right(source.starts, offset)
            point = row, offset - source.starts[row - 1] + 1
            end = offset + 1
            while end < len(source.raw) and source.raw[end] & 0xC0 == 0x80:
                end += 1
            value = {"file": str(path), "message": severity + ": " + diagnostic.spelling,
                     "line": point[0], "column": point[1], "end_column": point[1] + max(0, end - offset - 1),
                     "fatal": diagnostic.severity >= self.c.Diagnostic.Fatal}
            if value not in self.diagnostics:
                self.diagnostics.append(value)

    def preprocessing(self, tu) -> None:
        for cursor in tu.cursor.get_children():
            path = self.cursor_path(cursor)
            if path is None or not _is_owned(path, self.root):
                continue
            if cursor.kind.name == "INCLUSION_DIRECTIVE":
                try:
                    included = cursor.get_included_file()
                except AssertionError:
                    # cindex wraps a missing include's null CXFile with an
                    # assertion. The compiler diagnostic is retained below.
                    included = None
                if included:
                    target = self.file_path(included)
                    if target.is_file():
                        self.source(target)
                        self.edge("file:" + str(path), "file:" + str(target), "include", self.scope_location(cursor))
            elif cursor.kind.name == "MACRO_DEFINITION":
                self.symbol(cursor, "explicit", True)
            elif cursor.kind.name == "MACRO_INSTANTIATION" and cursor.referenced:
                target = self.symbol(cursor.referenced)
                self.edge("file:" + str(path), target, "macro_usage", self.token_location(cursor))

    def module_declarations(self, tu, main: Path) -> None:
        """Map accepted top-level module/import tokens without inventing AST nodes.

        libclang indexes exported entities but has no stable module-declaration
        cursor. The parser's tokens provide source provenance for module nodes.
        """
        tokens = list(tu.get_tokens(extent=tu.cursor.extent))
        depth = 0
        index = 0
        while index < len(tokens):
            token = tokens[index]
            word = token.spelling
            if word == "{":
                depth += 1
            elif word == "}":
                depth = max(0, depth - 1)
            if depth or word not in {"module", "import"}:
                index += 1
                continue
            end = index + 1
            while end < len(tokens) and tokens[end].spelling != ";":
                end += 1
            parts = tokens[index + 1:end]
            name = "".join(p.spelling for p in parts)
            if not parts or name.startswith(("<", '"', ":private")) or not re.fullmatch(r"[A-Za-z_]\w*(?:[.:][A-Za-z_]\w*)*", name):
                index = end + 1
                continue
            key = "cxx:module:" + name
            entry = self.symbols.setdefault(key, {
                "id": key, "name": [{"name": name, "prefix": "", "postfix": ""}],
                "kind": "module", "definition": "none", "delimiter": "::", "locations": [],
            })
            location = self.source(main).span(parts[0].extent.start.offset, parts[-1].extent.end.offset)
            if word == "module":
                self.modules[main] = name
                entry["definition"] = "explicit"
                self.add_location(entry, location)
            else:
                self.edge("file:" + str(main), key, "import", location)
            index = end + 1

    def result(self) -> dict[str, Any]:
        module_files = {name: path for path, name in self.modules.items()}
        for edge in list(self.edges.values()):
            if edge["kind"] == "import" and edge["target"].startswith("cxx:module:"):
                module = edge["target"][len("cxx:module:"):]
                if module in module_files:
                    for location in edge["locations"]:
                        self.edge(edge["source"], "file:" + str(module_files[module]), "import", location)
        for path, source in self.sources.items():
            if path.read_bytes() != source.raw:
                raise RuntimeError(f"Source changed during C++ indexing: {path}")
        for item in [*self.symbols.values(), *self.edges.values()]:
            item["locations"].sort(key=lambda v: (v["file"], v["start_line"], v["start_column"], v["end_line"], v["end_column"], v["kind"]))
        return {"files": [self.files[p] for p in sorted(self.files)],
                "symbols": [self.symbols[k] for k in sorted(self.symbols)],
                "edges": [self.edges[k] for k in sorted(self.edges)],
                "diagnostics": sorted(self.diagnostics, key=lambda d: (d["file"], d["line"], d["column"], d["message"]))}


def _index_callbacks(graph: _Graph, index, tu) -> None:
    """Narrow ctypes binding to the public Clang 18 indexing structures."""
    c = graph.c
    C = ctypes

    class IndexLocation(C.Structure):
        _fields_ = [("ptr_data", C.c_void_p * 2), ("int_data", C.c_uint)]

    class Entity(C.Structure):
        _fields_ = [("kind", C.c_int), ("template_kind", C.c_int), ("language", C.c_int),
                    ("name", C.c_char_p), ("usr", C.c_char_p), ("cursor", c.Cursor),
                    ("attributes", C.c_void_p), ("attribute_count", C.c_uint)]

    class Container(C.Structure):
        _fields_ = [("cursor", c.Cursor)]

    class Declaration(C.Structure):
        _fields_ = [("entity", C.POINTER(Entity)), ("cursor", c.Cursor), ("location", IndexLocation),
                    ("semantic", C.POINTER(Container)), ("lexical", C.POINTER(Container)),
                    ("redeclaration", C.c_int), ("definition", C.c_int), ("is_container", C.c_int),
                    ("container", C.POINTER(Container)), ("implicit", C.c_int),
                    ("attributes", C.c_void_p), ("attribute_count", C.c_uint), ("flags", C.c_uint)]

    class Reference(C.Structure):
        _fields_ = [("kind", C.c_int), ("cursor", c.Cursor), ("location", IndexLocation),
                    ("entity", C.POINTER(Entity)), ("parent", C.POINTER(Entity)),
                    ("container", C.POINTER(Container)), ("role", C.c_uint)]

    DeclarationCallback = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Declaration))
    ReferenceCallback = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Reference))

    class Callbacks(C.Structure):
        _fields_ = [("abort", C.c_void_p), ("diagnostics", C.c_void_p), ("entered", C.c_void_p),
                    ("included", C.c_void_p), ("imported", C.c_void_p), ("started", C.c_void_p),
                    ("declaration", DeclarationCallback), ("reference", ReferenceCallback)]

    errors: list[Exception] = []

    def cursor(value):
        value._tu = tu
        return value

    @DeclarationCallback
    def declaration_callback(_, pointer):
        try:
            info = pointer.contents
            current = cursor(info.cursor)
            path = graph.cursor_path(current)
            if path is None or not _is_owned(path, graph.root) or info.implicit:
                return
            identity = graph.symbol(current, "explicit" if info.definition else "none", True)
            if current.kind.name == "CXX_METHOD":
                overridden = C.POINTER(c.Cursor)()
                count = C.c_uint()
                c.conf.lib.clang_getOverriddenCursors(current, C.byref(overridden), C.byref(count))
                try:
                    for offset in range(count.value):
                        graph.edge(identity, graph.symbol(cursor(overridden[offset])), "override", graph.token_location(current))
                finally:
                    c.conf.lib.clang_disposeOverriddenCursors(overridden)
            if current.kind.name in {"STRUCT_DECL", "CLASS_DECL", "CLASS_TEMPLATE"}:
                for child in current.get_children():
                    if child.kind.name == "CXX_BASE_SPECIFIER" and child.referenced:
                        graph.edge(identity, graph.symbol(child.referenced), "inheritance", graph.token_location(child))
        except Exception as exc:
            errors.append(exc)

    @ReferenceCallback
    def reference_callback(_, pointer):
        try:
            info = pointer.contents
            if not info.entity or info.role & (1 << 8):
                return
            current = cursor(info.cursor)
            path = graph.cursor_path(current)
            if path is None or not _is_owned(path, graph.root):
                return
            target_cursor = current.referenced or cursor(info.entity.contents.cursor)
            target = graph.symbol(target_cursor)
            source = graph.symbol(cursor(info.parent.contents.cursor)) if info.parent else "file:" + str(path)
            if not source and info.container:
                source = graph.symbol(cursor(info.container.contents.cursor))
            source = source or "file:" + str(path)
            kind = "call" if info.role & (1 << 5) else "type_usage" if current.kind.name in {"TYPE_REF", "TEMPLATE_REF", "CXX_BASE_SPECIFIER"} else "usage"
            graph.edge(source, target, kind, graph.token_location(current))
        except Exception as exc:
            errors.append(exc)

    library = c.conf.lib
    library.clang_IndexAction_create.argtypes = [c.Index]
    library.clang_IndexAction_create.restype = C.c_void_p
    library.clang_IndexAction_dispose.argtypes = [C.c_void_p]
    library.clang_indexTranslationUnit.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(Callbacks), C.c_uint, C.c_uint, c.TranslationUnit]
    library.clang_indexTranslationUnit.restype = C.c_int
    library.clang_getOverriddenCursors.argtypes = [c.Cursor, C.POINTER(C.POINTER(c.Cursor)), C.POINTER(C.c_uint)]
    library.clang_disposeOverriddenCursors.argtypes = [C.POINTER(c.Cursor)]
    action = library.clang_IndexAction_create(index)
    if not action:
        raise RuntimeError("Clang failed to create an indexing action")
    try:
        callbacks = Callbacks(None, None, None, None, None, None, declaration_callback, reference_callback)
        result = library.clang_indexTranslationUnit(action, None, C.byref(callbacks), C.sizeof(callbacks), 0x2, tu)
        if errors:
            raise RuntimeError("Clang output could not be mapped to the common graph") from errors[0]
        if result:
            raise RuntimeError(f"Clang indexing failed with status {result}")
    finally:
        library.clang_IndexAction_dispose(action)


def index_project(root: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Index selected C/C++ translation units without executing build commands.

    A valid source diagnostic produces an incomplete graph. Engine, I/O, argument
    and protocol failures raise, so the caller can reject the candidate database.
    """
    root = Path(root).resolve()
    if options is not None and not isinstance(options, dict):
        raise ValueError("C++ options must be an object")
    options = options or {}
    if not root.is_dir():
        raise ValueError(f"C++ project root does not exist: {root}")
    c, _ = _clang()
    inputs: set[Path] = set()
    responses: set[Path] = set()
    commands = _commands(root, options, inputs, responses)
    graph = _Graph(root, c)
    for path in sorted(inputs):
        graph.source(path)
        # External response files are dependencies, not owned source roots.
        # Native refresh compares their stored contents and follows include
        # edges back to project translation units when they change.
        graph.files[path].update(language="config", indexed=_is_owned(path, root) or path not in responses)
    for source, _ in commands:
        graph.source(source)
        for dependency in inputs:
            graph.edge("file:" + str(source), "file:" + str(dependency), "include")
    index = c.Index.create()
    units = []
    for source, arguments in commands:
        try:
            unit = index.parse(str(source), args=arguments,
                               unsaved_files=[(str(source), graph.sources[source].raw)],
                               options=c.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        except c.TranslationUnitLoadError as exc:
            raise RuntimeError(f"Clang could not parse {source}; check flags and matching module BMI version") from exc
        units.append((source, unit))
        graph.module_declarations(unit, source)
    # Discover every module owner before mapping cross-TU symbol identities.
    for source, unit in units:
        graph.translation_unit = unit
        graph.preprocessing(unit)
        graph.record_diagnostics(unit, source)
        _index_callbacks(graph, index, unit)
    for path in sorted(_discover_observed_inputs(root) - graph.sources.keys()):
        source = graph.source(path)
        graph.files[path].update(active=False, complete=False)
        end = 1
        while end < len(source.raw) and source.raw[end] & 0xC0 == 0x80:
            end += 1
        graph.diagnostics.append({"file": str(path), "line": 1, "column": 1, "end_column": end, "fatal": False,
                                  "message": "Input observed for change detection but not parsed in the selected compilation configuration"})
    return graph.result()
