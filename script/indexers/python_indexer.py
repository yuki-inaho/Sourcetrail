"""Python 3.14 syntax and conservative, scope-aware source indexing.

The adapter never imports or executes indexed code. It records lexical names,
project imports, inheritance and statically resolvable calls. Dynamic dispatch is
reported as unresolved instead of inventing a call target.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import sys
import tokenize

from .graph import empty_graph


def capabilities() -> dict:
    return {
        "protocol_version": 1, "database_version": 25, "adapter": "python-ast",
        "engine": "CPython ast", "engine_version": ".".join(map(str, sys.version_info[:3])),
        "language": "Python", "syntax_version": "3.14", "coordinate_unit": "utf8-byte",
        "semantic_mode": "static-scoped", "partial_clearing": False,
        "capabilities": ["definitions", "project-imports", "relative-imports", "namespace-packages",
                         "lexical-references", "resolved-calls", "inheritance", "async-await",
                         "pattern-matching", "exception-groups", "type-parameters", "type-aliases",
                         "template-strings", "diagnostics"],
        "limitations": ["Dynamic imports, monkey-patching and general type inference are unresolved.",
                        "Project source roots are explicit; indexed code is never executed.",
                        "Non-identifier module paths are observed with a diagnostic, without invented import identities.",
                        "This is a separate static profile, not a replacement for Jedi type inference."],
    }


@dataclass
class Source:
    path: Path
    module: str
    content: str
    tree: ast.Module | None
    tokens: list[tokenize.TokenInfo]

    def column(self, line: int, character: int) -> int:
        return len(self.content.split("\n")[line - 1][:character].encode("utf-8")) + 1

    def location(self, node: ast.AST, *, name: str | None = None, kind: str = "token") -> dict:
        start_line, end_line = node.lineno, getattr(node, "end_lineno", node.lineno)
        start_column = node.col_offset + 1
        end_column = getattr(node, "end_col_offset", node.col_offset + 1)
        # ast parses UTF-8-sig without the BOM; storage retains the original bytes.
        bom = self.content.startswith("\ufeff")
        if start_line == 1 and bom:
            start_column += 3
        if end_line == 1 and bom:
            end_column += 3
        if name is not None:
            matching = [token for token in self.tokens if token.type == tokenize.NAME and token.string == name
                        and (token.start[0], self.column(*token.start)) >= (start_line, start_column)
                        and (token.end[0], self.column(*token.end) - 1) <= (end_line, end_column)]
            if matching:
                token = matching[-1] if isinstance(node, ast.Attribute) else matching[0]
                start_line, end_line = token.start[0], token.end[0]
                start_column, end_column = self.column(*token.start), self.column(*token.end) - 1
        if end_column == 0 and end_line > start_line:
            end_line -= 1
            end_column = len(self.content.split("\n")[end_line - 1].encode("utf-8"))
        return {"file": str(self.path), "start_line": start_line, "start_column": start_column,
                "end_line": end_line, "end_column": max(end_column, 1), "kind": kind}


@dataclass
class Scope:
    identity: str
    source: Source
    parent: Scope | None = None
    class_id: str | None = None
    kind: str = "module"
    bindings: dict[str, str | None] = field(default_factory=dict)
    instances: dict[str, str] = field(default_factory=dict)
    writes: dict[str, list[ast.AST | None]] = field(default_factory=dict)
    global_names: set[str] = field(default_factory=set)
    nonlocal_names: set[str] = field(default_factory=set)


class PythonProject:
    def __init__(self, root: Path, options: dict):
        self.root, self.options = root.resolve(), options
        if not self.root.is_dir():
            raise ValueError(f"Python project root does not exist: {self.root}")
        roots = options.get("source_roots", ["."])
        if not isinstance(roots, list) or not roots or any(not isinstance(p, str) or not p for p in roots):
            raise ValueError("Python source_roots must be a nonempty list of directories")
        version = options.get("python_version", (3, 14))
        if (not isinstance(version, (tuple, list)) or len(version) != 2
                or any(type(part) is not int for part in version) or version[0] != 3 or not 8 <= version[1] <= 14):
            raise ValueError("Python syntax version must be [3, minor] for minor 8 through 14")
        self.graph = empty_graph()
        self.sources: list[Source] = []
        self.symbols: dict[str, dict] = {}
        self.scopes: dict[int, Scope] = {}
        self.modules: dict[str, Scope] = {}
        self.pending_imports: list[tuple[Scope, ast.AST]] = []
        self.notices: set[tuple[str, int, str]] = set()
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.parents: dict[str, list[str]] = {}
        self.annotation_scopes: dict[int, Scope] = {}
        self.pending_writes: list[tuple[Scope, str, ast.AST, ast.AST | None]] = []
        self.uncertain_callables: set[str] = set()
        self.source_roots = [(self.root / p).resolve() for p in roots]
        if any(not path.is_dir() for path in self.source_roots):
            raise ValueError("A configured Python source root does not exist")

    def add_symbol(self, identity: str, kind: str, source: Source | None = None,
                   node: ast.AST | None = None, *, name: str | None = None, implicit: bool = False) -> str:
        if identity not in self.symbols:
            self.symbols[identity] = {"id": identity, "name": identity.split("."), "delimiter": ".",
                                      "kind": kind, "definition": "implicit" if implicit else ("explicit" if node else "none"),
                                      "locations": []}
        symbol = self.symbols[identity]
        if source is not None and node is not None:
            symbol["locations"].append(source.location(node, name=name))
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol["locations"].append(source.location(node, kind="scope"))
        return identity

    def edge(self, source: str, target: str, kind: str, location: dict | None = None) -> None:
        key = (source, target, kind)
        edge = self.edges.setdefault(key, {"source": source, "target": target, "kind": kind, "locations": []})
        if location is not None and location not in edge["locations"]:
            edge["locations"].append(location)

    def diagnostic(self, source: Source, node: ast.AST | None, message: str, *, fatal: bool = False,
                   line: int | None = None, column: int | None = None) -> None:
        line = line or getattr(node, "lineno", 1)
        lines = source.content.split("\n")
        line = min(max(line, 1), len(lines))
        encoded = lines[line - 1].encode("utf-8")
        column = column or (getattr(node, "col_offset", 0) + 1 + (3 if node is not None and line == 1 and source.content.startswith("\ufeff") else 0))
        column = min(max(column, 1), len(encoded) + 1)
        while column > 1 and column <= len(encoded) and encoded[column - 1] & 0xC0 == 0x80:
            column -= 1
        end = column
        while end < len(encoded) and encoded[end] & 0xC0 == 0x80:
            end += 1
        key = (str(source.path), line, message)
        if key not in self.notices:
            self.notices.add(key)
            self.graph["diagnostics"].append({"file": str(source.path), "message": message, "line": line,
                                               "column": column, "end_column": end, "fatal": fatal})
            next(file for file in self.graph["files"] if file["path"] == str(source.path))["complete"] = False

    def load(self) -> None:
        excluded = {".git", ".pixi", ".venv", "venv", "__pycache__", "build", "target"}
        discovered: set[Path] = set()
        for source_root in self.source_roots:
            for directory, children, filenames in os.walk(source_root):
                children[:] = sorted(name for name in children if name not in excluded)
                discovered.update((Path(directory) / name).resolve() for name in filenames if name.endswith(".py"))
        paths = sorted(discovered)
        for path in paths:
            if not any(path.is_relative_to(base) for base in self.source_roots):
                raise ValueError(f"Python source symlink leaves configured source roots: {path}")
            relative = next(path.relative_to(base) for base in self.source_roots if path.is_relative_to(base))
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            module = ".".join(parts) or path.parent.name
            content = path.read_bytes().decode("utf-8")
            self.graph["files"].append({"path": str(path), "content": content, "language": "python", "indexed": True, "complete": True})
            source = Source(path, module, content, None, [])
            self.sources.append(source)
            if not all(part.isidentifier() for part in (parts or [path.parent.name])):
                self.diagnostic(source, None,
                                "Python module path contains a non-identifier component; observed without import/name resolution",
                                fatal=True)
                continue
            try:
                decoded = content[1:] if content.startswith("\ufeff") else content
                source.tree = ast.parse(decoded, filename=str(path), type_comments=True,
                                        feature_version=tuple(self.options.get("python_version", (3, 14))))
                # ast.parse alone accepts return/break outside a function/loop
                # and invalid nonlocal declarations. Compile validates scopes
                # and creates a code object, but never executes indexed code.
                compile(source.tree, str(path), "exec", dont_inherit=True)
                # tokenize byte input handles BOM and encoding declarations without executing code.
                encoding, _ = tokenize.detect_encoding(io.BytesIO(content.encode("utf-8")).readline)
                if encoding not in ("utf-8", "utf-8-sig"):
                    raise ValueError("The modern Python profile requires UTF-8 source encoding")
                source.tokens = list(tokenize.tokenize(io.BytesIO(content.encode("utf-8")).readline))
                if content.startswith("\ufeff"):
                    source.tokens = [token._replace(start=(token.start[0], token.start[1] + (token.start[0] == 1)),
                                                     end=(token.end[0], token.end[1] + (token.end[0] == 1)))
                                     for token in source.tokens]
            except (SyntaxError, ValueError, tokenize.TokenError) as error:
                source.tree = None
                line = getattr(error, "lineno", 1) or 1
                lines = content.split("\n")
                line = min(max(line, 1), len(lines))
                error_text = lines[line - 1]
                bom_bytes = 3 if line == 1 and error_text.startswith("\ufeff") else 0
                if bom_bytes:
                    error_text = error_text[1:]
                character = max((getattr(error, "offset", 1) or 1) - 1, 0)
                column = len(error_text[:character].encode("utf-8")) + 1 + bom_bytes
                self.diagnostic(source, None, f"Python syntax: {getattr(error, 'msg', str(error))}", fatal=True,
                                line=line, column=column)
            if module in self.modules:
                self.diagnostic(source, None, f"Ambiguous module {module}: multiple source roots provide it", fatal=True)
                continue
            self.add_symbol(module, "module", source)
            self.symbols[module]["definition"] = "explicit"
            scope = Scope(module, source)
            self.modules[module] = scope
            if source.tree is not None:
                self.scopes[id(source.tree)] = scope
                self.declare(source.tree, scope)

    def bind(self, scope: Scope, name: str, identity: str) -> None:
        if name in scope.bindings and scope.bindings[name] != identity:
            self.diagnostic(scope.source, None, f"Ambiguous binding: {name}")
            scope.bindings[name] = None
        else:
            scope.bindings[name] = identity

    @staticmethod
    def arguments(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> list[ast.arg]:
        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        return args + [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]

    def directives(self, node: ast.AST, scope: Scope) -> None:
        """Collect directives in this lexical scope, without entering nested ones."""
        if isinstance(node, ast.Global):
            scope.global_names.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            scope.nonlocal_names.update(node.names)
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            for child in ast.iter_child_nodes(node):
                self.directives(child, scope)

    def write(self, scope: Scope, name: str, node: ast.AST, value: ast.AST | None,
              *, originating: Scope | None = None) -> None:
        """Track every possible write; a lexical declaration is not a runtime type."""
        origin = originating or scope
        if originating is None and (name in scope.global_names or name in scope.nonlocal_names):
            self.pending_writes.append((scope, name, node, value))
            return
        scope.writes.setdefault(name, []).append(value if origin is scope else None)
        previous = scope.bindings.get(name)
        if name not in scope.bindings:
            identity = scope.identity + "." + name
            kind = "field" if scope.kind == "class" else ("global_variable" if scope.parent is None else "symbol")
            self.add_symbol(identity, kind, origin.source, node, name=name)
            scope.bindings[name] = identity
            self.edge(scope.identity, identity, "member")
        elif previous and self.symbols[previous]["kind"] in ("function", "method", "class", "module"):
            # A later assignment may replace a callable/import. Keep its source
            # declaration, but never use it as proof of a resolved call.
            scope.bindings[name] = None
            self.diagnostic(origin.source, node, f"Rebound name is unresolved: {name}")
        scope.instances.pop(name, None)

    def target(self, node: ast.AST, scope: Scope, value: ast.AST | None = None) -> None:
        if isinstance(node, ast.Name):
            self.write(scope, node.id, node, value)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self.target(element, scope)
        elif isinstance(node, ast.Starred):
            self.target(node.value, scope)

    def finish_writes(self) -> None:
        for scope, name, node, value in self.pending_writes:
            target = self.binding_owner(scope, name)
            if target is None:
                self.diagnostic(scope.source, node, f"Unresolved nonlocal binding: {name}")
            else:
                self.write(target, name, node, value, originating=scope)

    def binding_owner(self, scope: Scope, name: str) -> Scope | None:
        if name in scope.global_names:
            return self.modules[scope.source.module]
        if name in scope.nonlocal_names:
            target = scope.parent
            while target is not None and (target.kind == "class" or name not in target.bindings):
                target = target.parent
            return target if target is not None and target.kind != "module" else None
        return scope

    def declare(self, node: ast.AST, scope: Scope) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self.pending_imports.append((scope, node))
            return
        if isinstance(node, ast.Global):
            scope.global_names.update(node.names)
            return
        if isinstance(node, ast.Nonlocal):
            scope.nonlocal_names.update(node.names)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            is_class = isinstance(node, ast.ClassDef)
            is_lambda = isinstance(node, ast.Lambda)
            name = f"<lambda@{node.lineno}:{node.col_offset}>" if is_lambda else node.name
            identity = scope.identity + "." + name
            kind = "class" if is_class else ("method" if scope.kind == "class" and not is_lambda else "function")
            self.add_symbol(identity, kind, scope.source, node, name=None if is_lambda else name)
            if not is_lambda:
                if name in scope.bindings:
                    scope.bindings[name] = None
                    self.diagnostic(scope.source, node, f"Multiple bindings are unresolved: {name}")
                else:
                    self.bind(scope, name, identity)
            self.edge(scope.identity, identity, "member")
            nested = Scope(identity, scope.source, scope, identity if is_class else scope.class_id,
                           "class" if is_class else "lambda" if is_lambda else "function")
            self.scopes[id(node)] = nested
            annotation = Scope(identity, scope.source, scope, kind="annotation")
            self.annotation_scopes[id(node)] = annotation
            for parameter in getattr(node, "type_params", []):
                parameter_id = identity + "." + parameter.name
                self.add_symbol(parameter_id, "type_parameter", scope.source, parameter, name=parameter.name)
                nested.bindings[parameter.name] = parameter_id
                annotation.bindings[parameter.name] = parameter_id
                self.edge(identity, parameter_id, "member")
            decorators = getattr(node, "decorator_list", [])
            decorator_names = {decorator.id for decorator in decorators if isinstance(decorator, ast.Name)}
            if decorators and (is_class or len(decorator_names) != len(decorators)
                               or not decorator_names <= {"staticmethod", "classmethod"}):
                self.uncertain_callables.add(identity)
            if not is_class:
                args = self.arguments(node)
                for arg in args:
                    argument = identity + "." + arg.arg
                    self.add_symbol(argument, "symbol", scope.source, arg, name=arg.arg)
                    nested.bindings[arg.arg] = argument
                    self.edge(identity, argument, "member")
                if scope.kind == "class" and args and "staticmethod" not in decorator_names and not is_lambda:
                    nested.instances[args[0].arg] = scope.identity
                for default in node.args.defaults + [value for value in node.args.kw_defaults if value is not None]:
                    self.declare(default, scope)
            body = [node.body] if is_lambda else node.body
            for statement in body:
                self.directives(statement, nested)
            for statement in body:
                self.declare(statement, nested)
            # Expressions in a definition header belong to the enclosing scope.
            for decorator in decorators:
                self.declare(decorator, scope)
            if is_class:
                for expression in node.bases + [keyword.value for keyword in node.keywords]:
                    self.declare(expression, annotation)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            identity = scope.identity + f".<comprehension@{node.lineno}:{node.col_offset}>"
            self.add_symbol(identity, "function", scope.source, node)
            self.edge(scope.identity, identity, "member")
            nested = Scope(identity, scope.source, scope, scope.class_id, "comprehension")
            self.scopes[id(node)] = nested
            for index, generator in enumerate(node.generators):
                self.target(generator.target, nested)
                self.declare(generator.iter, scope if index == 0 else nested)
                for condition in generator.ifs:
                    self.declare(condition, nested)
            for expression in ([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]):
                self.declare(expression, nested)
            return
        if isinstance(node, ast.TypeAlias):
            name = node.name.id
            identity = scope.identity + "." + name
            self.add_symbol(identity, "typedef", scope.source, node.name, name=name)
            self.bind(scope, name, identity)
            self.edge(scope.identity, identity, "member")
            nested = Scope(identity, scope.source, scope, kind="annotation")
            self.scopes[id(node)] = nested
            for parameter in node.type_params:
                param_id = identity + "." + parameter.name
                self.add_symbol(param_id, "type_parameter", scope.source, parameter, name=parameter.name)
                nested.bindings[parameter.name] = param_id
                self.edge(identity, param_id, "member")
            self.declare(node.value, nested)
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            owner = scope
            if isinstance(node, ast.NamedExpr):
                while owner.kind == "comprehension" and owner.parent is not None:
                    owner = owner.parent
            for target in targets:
                self.target(target, owner, None if isinstance(node, ast.AugAssign) else node.value)
            if node.value is not None:
                self.declare(node.value, scope)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            self.target(node.target, scope)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    self.target(item.optional_vars, scope)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            self.write(scope, node.name, node, None)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                self.target(target, scope)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            self.write(scope, node.name, node, None)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            self.write(scope, node.rest, node, None)
        for child in ast.iter_child_nodes(node):
            self.declare(child, scope)

    def link_imports(self) -> None:
        for scope, node in self.pending_imports:
            if isinstance(node, ast.Import):
                imports = [(alias.name, alias.asname or alias.name.split(".")[0],
                            alias.name if alias.asname else alias.name.split(".")[0]) for alias in node.names]
            else:
                prefix = scope.source.module.split(".")
                if scope.source.path.name != "__init__.py":
                    prefix.pop()
                if node.level:
                    if node.level > len(prefix):
                        self.diagnostic(scope.source, node, "Relative import goes beyond the top-level package", fatal=True)
                        for alias in node.names:
                            if alias.name != "*":
                                scope.bindings[alias.asname or alias.name] = None
                        continue
                    prefix = prefix[:len(prefix) - node.level + 1]
                    base = ".".join(prefix + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                imports = [(base, alias.asname or alias.name, base + "." + alias.name) for alias in node.names]
            for module, local, target in imports:
                if local == "*":
                    self.diagnostic(scope.source, node, "Wildcard imports require explicit names in the static profile")
                    continue
                if target not in self.symbols:
                    if target in self.modules or any(name.startswith(target + ".") for name in self.modules):
                        self.add_symbol(target, "module")
                    else:
                        self.add_symbol(target, "symbol")
                        self.diagnostic(scope.source, node, f"Unresolved import: {target}")
                owner = self.binding_owner(scope, local)
                if owner is None:
                    self.diagnostic(scope.source, node, f"Unresolved import binding: {local}")
                    continue
                self.bind(owner, local, target)
                self.edge(scope.identity, target, "import", scope.source.location(node, name=local))
                dependency = self.modules.get(module) or self.modules.get(target)
                if dependency:
                    self.edge("file:" + str(scope.source.path), "file:" + str(dependency.source.path), "import")

    def lookup(self, name: str, scope: Scope) -> str | None:
        if name in scope.global_names:
            scope = self.modules[scope.source.module]
        elif name in scope.nonlocal_names:
            parent = scope.parent
            while parent is not None and (parent.kind == "class" or name not in parent.bindings):
                parent = parent.parent
            if parent is None or parent.kind == "module":
                return None
            scope = parent
        current = scope
        while current:
            if name in current.bindings:
                return current.bindings[name]
            current = current.parent
            # A method's unqualified names do not resolve through its class body.
            if current and current.class_id == current.identity and scope.class_id == current.identity:
                current = current.parent
        if name in vars(builtins):
            value = vars(builtins)[name]
            return self.add_symbol("builtins." + name, "builtin_type" if isinstance(value, type) else "function", implicit=True)
        return None

    def member(self, owner: str, name: str, visited: set[str] | None = None) -> str | None:
        visited = visited or set()
        if owner in visited:
            return None
        visited.add(owner)
        identity = owner + "." + name
        if identity in self.symbols:
            return identity
        candidates = {result for base in self.parents.get(owner, []) if (result := self.member(base, name, visited))}
        return next(iter(candidates)) if len(candidates) == 1 else None

    def resolve(self, node: ast.AST, scope: Scope) -> str | None:
        if isinstance(node, ast.Name):
            return self.lookup(node.id, scope)
        if isinstance(node, ast.Attribute):
            owner = None
            if isinstance(node.value, ast.Name):
                owner = scope.instances.get(node.value.id)
            if isinstance(node.value, ast.Call):
                candidate = self.resolve(node.value.func, scope)
                if candidate and self.symbols[candidate]["kind"] in ("class", "builtin_type") and candidate not in self.uncertain_callables:
                    owner = candidate
            owner = owner or self.resolve(node.value, scope)
            return self.member(owner, node.attr) if owner and self.symbols[owner]["kind"] in ("module", "class", "builtin_type") else None
        if isinstance(node, ast.Subscript):
            return self.resolve(node.value, scope)
        return None

    def link_inheritance(self) -> None:
        # Build every base relation before resolving an inherited method from a
        # different module. Source filename ordering must not change its target.
        for source in self.sources:
            if source.tree is None:
                continue
            for node in ast.walk(source.tree):
                if not isinstance(node, ast.ClassDef) or id(node) not in self.scopes:
                    continue
                nested = self.scopes[id(node)]
                annotation = self.annotation_scopes[id(node)]
                for base in node.bases:
                    target = self.resolve(base, annotation)
                    if target and self.symbols[target]["kind"] in ("class", "builtin_type"):
                        self.parents.setdefault(nested.identity, []).append(target)
                        self.edge(nested.identity, target, "inheritance", source.location(base))
                    else:
                        self.diagnostic(source, base, f"Unresolved base: {ast.unparse(base)}")

    def references(self, node: ast.AST, scope: Scope) -> None:
        nested = self.scopes.get(id(node))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            if nested is None:
                return
            annotation = self.annotation_scopes[id(node)]
            for decorator in getattr(node, "decorator_list", []):
                self.references(decorator, scope)
            for parameter in getattr(node, "type_params", []):
                for child in ast.iter_child_nodes(parameter):
                    self.references(child, annotation)
            if isinstance(node, ast.ClassDef):
                for expression in node.bases + [keyword.value for keyword in node.keywords]:
                    self.references(expression, annotation)
            else:
                # Default expressions run at definition time in the enclosing
                # scope. Parameter bindings exist only in the callable body.
                for default in node.args.defaults + [value for value in node.args.kw_defaults if value is not None]:
                    self.references(default, scope)
                for argument in self.arguments(node):
                    if argument.annotation is not None:
                        self.references(argument.annotation, annotation)
                returns = getattr(node, "returns", None)
                if returns is not None:
                    self.references(returns, annotation)
            for statement in ([node.body] if isinstance(node, ast.Lambda) else node.body):
                self.references(statement, nested)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if nested is None:
                return
            for index, generator in enumerate(node.generators):
                self.references(generator.iter, scope if index == 0 else nested)
                for condition in generator.ifs:
                    self.references(condition, nested)
            for expression in ([node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]):
                self.references(expression, nested)
            return
        if isinstance(node, ast.TypeAlias):
            if nested is not None:
                for parameter in node.type_params:
                    for child in ast.iter_child_nodes(parameter):
                        self.references(child, nested)
                self.references(node.value, nested)
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if node.value is not None:
                self.references(node.value, scope)
            if isinstance(node, ast.AnnAssign):
                self.references(node.annotation, scope)
                annotated = self.resolve(node.annotation, scope)
                if annotated:
                    for target in targets:
                        symbol = self.resolve(target, scope)
                        if symbol:
                            self.edge(symbol, annotated, "type_usage", scope.source.location(node.annotation))
            inferred = self.resolve(node.value.func, scope) if isinstance(node.value, ast.Call) else None
            for target in targets:
                if isinstance(target, ast.Name):
                    scope.instances.pop(target.id, None)
                    if (len(scope.writes.get(target.id, [])) == 1 and inferred
                            and inferred not in self.uncertain_callables
                            and self.symbols[inferred]["kind"] in ("class", "builtin_type")):
                        scope.instances[target.id] = inferred
                elif isinstance(target, ast.Attribute):
                    # A source-level monkey patch invalidates an earlier method
                    # assumption, even if its new value cannot be inferred.
                    previous = self.resolve(target, scope)
                    if previous:
                        self.uncertain_callables.add(previous)
            return
        if isinstance(node, ast.Call):
            target = self.resolve(node.func, scope)
            if (target and target not in self.uncertain_callables
                    and self.symbols[target]["kind"] in ("function", "method", "class", "builtin_type")):
                self.edge(scope.identity, target, "call", scope.source.location(node.func, name=getattr(node.func, "attr", None)))
            else:
                self.diagnostic(scope.source, node.func, f"Unresolved call: {ast.unparse(node.func)}")
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            target = self.resolve(node, scope)
            if target:
                self.edge(scope.identity, target, "usage", scope.source.location(node, name=node.attr))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            target = self.resolve(node, scope)
            if target:
                self.edge(scope.identity, target, "usage", scope.source.location(node, name=node.id))
        for child in ast.iter_child_nodes(node):
            self.references(child, scope)

    def run(self) -> dict:
        self.load()
        self.finish_writes()
        self.link_imports()
        self.link_inheritance()
        for source in self.sources:
            if source.tree is not None and id(source.tree) in self.scopes:
                self.references(source.tree, self.scopes[id(source.tree)])
        self.graph["symbols"] = list(self.symbols.values())
        self.graph["edges"] = list(self.edges.values())
        return self.graph


def index_project(root: Path, options: dict | None = None) -> dict:
    if sys.version_info[:2] != (3, 14):
        raise RuntimeError("The python-ast adapter requires the locked Python 3.14 runtime")
    if options is not None and not isinstance(options, dict):
        raise ValueError("Python adapter options must be an object")
    return PythonProject(Path(root), options or {}).run()
