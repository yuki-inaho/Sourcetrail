"""Independent acceptance cases for the modern Python source profile."""

from pathlib import Path

import pytest

from script.indexers.graph import validate_graph
from script.indexers.python_indexer import capabilities, index_project


def index(tmp_path, sources, options=None):
    for name, text in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    graph = index_project(tmp_path, options or {})
    validate_graph(graph)
    return graph


def edges(graph, kind):
    return {(edge["source"], edge["target"]) for edge in graph["edges"] if edge["kind"] == kind}


@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize("newline,final", [("\n", True), ("\n", False), ("\r\n", True), ("\r\n", False)])
def test_unicode_positions_are_exact_utf8_byte_ranges(tmp_path, bom, newline, final):
    source = "def 日本語(値):\n    return 値\n\ndef caller():\n    return 日本語(1)\n"
    source = source.replace("\n", newline)
    if not final:
        source = source.rstrip("\r\n")
    if bom:
        source = "\ufeff" + source
    graph = index(tmp_path, {"入力.py": source})
    assert graph["files"][0]["content"] == source
    assert not graph["diagnostics"]
    assert ("入力.caller", "入力.日本語") in edges(graph, "call")
    symbol = next(s for s in graph["symbols"] if s["id"] == "入力.日本語")
    location = next(loc for loc in symbol["locations"] if loc["kind"] == "token")
    assert source.split("\n")[location["start_line"] - 1].encode("utf-8")[
        location["start_column"] - 1:location["end_column"]].decode("utf-8") == "日本語"


def test_modern_syntax_records_declarations_and_references(tmp_path):
    graph = index(tmp_path, {"modern.py": '''
type Pair[T] = tuple[T, T]
class Box[T]:
    def value(self):
        return 7
def identity[T](value: T) -> T:
    return value
async def task(value):
    match value:
        case {"value": captured}:
            return identity(captured)
    try:
        raise ExceptionGroup("problem", [ValueError("bad")])
    except* ValueError:
        pass
name = "world"
message = t"hello {name}"
'''})
    symbols = {symbol["id"]: symbol for symbol in graph["symbols"]}
    assert symbols["modern.Pair"]["kind"] == "typedef"
    assert symbols["modern.Box.T"]["kind"] == "type_parameter"
    assert symbols["modern.identity.T"]["kind"] == "type_parameter"
    assert symbols["modern.Box.value"]["kind"] == "method"
    assert ("modern.task", "modern.identity") in edges(graph, "call")
    assert not graph["diagnostics"]


def test_relative_import_namespace_package_alias_and_inheritance(tmp_path):
    graph = index(tmp_path, {
        "pkg/base.py": "class Base:\n    def result(self):\n        return 5\n",
        "pkg/use.py": "from .base import Base as Parent\nclass Child(Parent):\n    def run(self):\n        return self.result()\n",
        "main.py": "from pkg.use import Child\ndef run():\n    value = Child()\n    return value.run()\n",
    })
    assert ("pkg.use.Child", "pkg.base.Base") in edges(graph, "inheritance")
    assert ("pkg.use.Child.run", "pkg.base.Base.result") in edges(graph, "call")
    assert ("main.run", "pkg.use.Child.run") in edges(graph, "call")
    assert ("file:" + str(tmp_path / "pkg/use.py"), "file:" + str(tmp_path / "pkg/base.py")) in edges(graph, "import")
    assert not graph["diagnostics"]


def test_scopes_do_not_resolve_method_names_through_class_scope(tmp_path):
    graph = index(tmp_path, {"scope.py": "def target():\n    return 1\nclass Box:\n    def target(self):\n        return 2\n    def call(self):\n        return target()\n"})
    assert ("scope.Box.call", "scope.target") in edges(graph, "call")
    assert ("scope.Box.call", "scope.Box.target") not in edges(graph, "call")


def test_dynamic_call_stays_unresolved_instead_of_fabricating_a_target(tmp_path):
    graph = index(tmp_path, {"dynamic.py": "def run(obj):\n    return obj.method()\n"})
    assert not edges(graph, "call")
    assert any("Unresolved call" in diagnostic["message"] for diagnostic in graph["diagnostics"])
    assert not graph["files"][0]["complete"]


@pytest.mark.parametrize("path", [".hidden/main.py", "a.b/main.py", "a.b.py", "bad-name/main.py"])
def test_nonidentifier_module_paths_are_observed_and_diagnosed(tmp_path, path):
    graph = index(tmp_path, {path: "def preserved():\n    return 1\n"})
    assert graph["files"][0]["indexed"]
    assert not graph["files"][0]["complete"]
    assert not graph["symbols"]
    assert any("non-identifier" in diagnostic["message"] for diagnostic in graph["diagnostics"])


def test_explicit_source_root_can_exclude_a_nonidentifier_parent(tmp_path):
    graph = index(tmp_path, {"a.b/main.py": "def preserved():\n    return 1\n"}, {"source_roots": ["a.b"]})
    assert not graph["diagnostics"]
    assert any(symbol["id"] == "main.preserved" for symbol in graph["symbols"])


def test_syntax_error_is_diagnostic_and_repair_rebuilds_cleanly(tmp_path):
    graph = index(tmp_path, {"broken.py": "def broken(:\n"})
    assert len(graph["diagnostics"]) == 1
    assert graph["diagnostics"][0]["fatal"]
    repaired = index(tmp_path, {"broken.py": "def repaired():\n    return 1\n"})
    assert not repaired["diagnostics"]
    assert "broken.repaired" in {symbol["id"] for symbol in repaired["symbols"]}
    assert "broken.broken" not in {symbol["id"] for symbol in repaired["symbols"]}


def test_imports_never_execute_source_code(tmp_path):
    marker = tmp_path / "must-not-exist"
    graph = index(tmp_path, {"unsafe.py": f"open({str(marker)!r}, 'w').write('executed')\ndef value():\n    return 1\n",
                             "use.py": "from unsafe import value\nresult = value()\n"})
    assert not marker.exists()
    assert ("use", "unsafe.value") in edges(graph, "call")


def test_unknown_import_and_shadowing_are_explicit(tmp_path):
    graph = index(tmp_path, {"use.py": "from missing import function\ndef run():\n    function = 42\n    return function()\n"})
    assert any("Unresolved import" in diagnostic["message"] for diagnostic in graph["diagnostics"])
    # A lexical variable is not evidence of a callable, nor of the shadowed import.
    assert not edges(graph, "call")
    assert any("Unresolved call" in diagnostic["message"] for diagnostic in graph["diagnostics"])


def test_capability_profile_is_versioned(tmp_path):
    profile = capabilities()
    assert profile["protocol_version"] == 1
    assert profile["database_version"] == 25
    assert profile["engine_version"].startswith("3.14.")
    assert profile["semantic_mode"] == "static-scoped"


def test_empty_source_and_deleted_source_are_valid_inputs(tmp_path):
    graph = index(tmp_path, {"empty.py": ""})
    assert graph["files"][0]["content"] == ""
    (tmp_path / "empty.py").unlink()
    assert index_project(tmp_path, {}) == {"files": [], "symbols": [], "edges": [], "diagnostics": []}


@pytest.mark.parametrize("replacement", ["42", "object()", "unknown()"])
def test_reassignment_invalidates_an_earlier_instance_type(tmp_path, replacement):
    graph = index(tmp_path, {"case.py": "class A:\n    def method(self): return 1\ndef run():\n    value = A()\n    value = " + replacement + "\n    return value.method()\n"})
    assert ("case.run", "case.A.method") not in edges(graph, "call")
    assert any("Unresolved call: value.method" in d["message"] for d in graph["diagnostics"])


@pytest.mark.parametrize("replacement", ["target = 42", "target += 1", "del target"])
def test_rebinding_a_function_does_not_keep_its_old_call_target(tmp_path, replacement):
    graph = index(tmp_path, {"case.py": "def target(): return 1\n" + replacement + "\ndef run(): return target()\n"})
    assert ("case.run", "case.target") not in edges(graph, "call")
    assert not graph["files"][0]["complete"]


def test_lambda_parameter_shadows_module_function(tmp_path):
    graph = index(tmp_path, {"case.py": "def target(): return 1\nrun = lambda target: target()\n"})
    assert not edges(graph, "call")
    assert any("Unresolved call: target" in d["message"] for d in graph["diagnostics"])
    assert any("<lambda@" in symbol["id"] for symbol in graph["symbols"])


def test_annotations_do_not_override_the_observed_constructor(tmp_path):
    graph = index(tmp_path, {"case.py": "class A:\n    def method(self): return 1\nclass B:\n    def method(self): return 2\ndef run():\n    value: A = B()\n    return value.method()\n"})
    assert ("case.run", "case.B.method") in edges(graph, "call")
    assert ("case.run", "case.A.method") not in edges(graph, "call")
    assert ("case.run.value", "case.A") in edges(graph, "type_usage")


def test_annotation_alone_is_not_proof_of_a_runtime_instance(tmp_path):
    graph = index(tmp_path, {"case.py": "class A:\n    def method(self): return 1\ndef run(value):\n    value: A\n    return value.method()\n"})
    assert ("case.run", "case.A.method") not in edges(graph, "call")
    assert any("Unresolved call: value.method" in d["message"] for d in graph["diagnostics"])


def test_exception_target_shadows_the_module_function(tmp_path):
    graph = index(tmp_path, {"case.py": "def target(): return 1\ndef run():\n    try: pass\n    except Exception as target:\n        return target()\n"})
    assert ("case.run", "case.target") not in edges(graph, "call")
    assert any("Unresolved call: target" in d["message"] for d in graph["diagnostics"])


@pytest.mark.parametrize("definition", ["def run(target=target()): return target", "run = lambda target=target(): target"])
def test_defaults_use_the_enclosing_scope_before_parameter_binding(tmp_path, definition):
    graph = index(tmp_path, {"case.py": "def target(): return 1\n" + definition + "\n"})
    assert edges(graph, "call") == {("case", "case.target")}
    assert not graph["diagnostics"]


def test_parameter_names_do_not_shadow_their_annotation_scope(tmp_path):
    graph = index(tmp_path, {"case.py": "class Value: pass\ndef run(Value: Value) -> Value:\n    return Value\n"})
    assert ("case.run", "case.Value") in edges(graph, "usage")
    assert ("case.run", "case.run.Value") in edges(graph, "usage")


@pytest.mark.parametrize("expression", ["[target() for target in []]", "{target() for target in []}",
                                         "{target(): 1 for target in []}", "(target() for target in [])"])
def test_comprehensions_have_an_isolated_binding_scope(tmp_path, expression):
    graph = index(tmp_path, {"case.py": "def target(): return 1\ndef run():\n    " + expression + "\n    return target()\n"})
    assert edges(graph, "call") == {("case.run", "case.target")}
    assert any("Unresolved call: target" in d["message"] for d in graph["diagnostics"])


def test_first_comprehension_iterable_runs_in_the_enclosing_scope(tmp_path):
    graph = index(tmp_path, {"case.py": "def target(): return []\ndef run():\n    return [target for target in target()]\n"})
    assert edges(graph, "call") == {("case.run", "case.target")}
    assert not graph["diagnostics"]


def test_possible_instance_types_from_different_branches_are_not_collapsed(tmp_path):
    graph = index(tmp_path, {"case.py": "class A:\n    def method(self): return 1\nclass B:\n    def method(self): return 2\ndef run(flag):\n    if flag: value = A()\n    else: value = B()\n    return value.method()\n"})
    assert not ({("case.run", "case.A.method"), ("case.run", "case.B.method")} & edges(graph, "call"))
    assert any("Unresolved call: value.method" in d["message"] for d in graph["diagnostics"])


@pytest.mark.parametrize("source,caller,target", [
    ("def target(): return 1\ndef change():\n    global target\n    target = 42\ndef run(): return target()\n", "case.run", "case.target"),
    ("def outer():\n    def target(): return 1\n    def change():\n        nonlocal target\n        target = 42\n    return target()\n", "case.outer", "case.outer.target"),
])
def test_global_and_nonlocal_writes_invalidate_callable_assumptions(tmp_path, source, caller, target):
    graph = index(tmp_path, {"case.py": source})
    assert (caller, target) not in edges(graph, "call")
    assert any("Unresolved call: target" in d["message"] for d in graph["diagnostics"])


def test_global_import_rebinding_does_not_resolve_the_old_module_function(tmp_path):
    graph = index(tmp_path, {"other.py": "def target(): return 2\n",
                             "case.py": "def target(): return 1\ndef run():\n    global target\n    from other import target\n    return target()\n"})
    assert ("case.run", "case.target") not in edges(graph, "call")
    assert any("Unresolved call: target" in d["message"] for d in graph["diagnostics"])


def test_nonlocal_skips_class_namespace_and_finds_enclosing_function(tmp_path):
    graph = index(tmp_path, {"case.py": "def outer():\n    def target(): return 1\n    class Box:\n        target = 42\n        def run(self):\n            nonlocal target\n            return target()\n"})
    assert ("case.outer.Box.run", "case.outer.target") in edges(graph, "call")
    assert not graph["diagnostics"]


@pytest.mark.parametrize("source", ["return 1\n", "break\n", "def run():\n    nonlocal absent\n",
                                    "def run(x, x): pass\n", "def run():\n    try: pass\n    except* ValueError: return None\n"])
def test_compilation_scope_errors_are_diagnostics_without_execution(tmp_path, source):
    graph = index(tmp_path, {"bad.py": source})
    assert graph["diagnostics"] and all(d["fatal"] for d in graph["diagnostics"])
    assert not graph["files"][0]["complete"]
    assert not edges(graph, "call")


def test_relative_import_above_package_root_does_not_become_absolute(tmp_path):
    graph = index(tmp_path, {"base.py": "def target(): return 1\n",
                             "pkg/use.py": "from ...base import target\ndef run(): return target()\n"})
    assert ("pkg.use.run", "base.target") not in edges(graph, "call")
    assert any("beyond the top-level package" in d["message"] for d in graph["diagnostics"])


@pytest.mark.parametrize("bom", [False, True])
def test_unicode_syntax_diagnostic_uses_byte_columns(tmp_path, bom):
    source = ("\ufeff" if bom else "") + "変数 = ;\n"
    graph = index(tmp_path, {"bad.py": source})
    diagnostic = graph["diagnostics"][0]
    assert diagnostic["column"] == 10 + (3 if bom else 0)
    raw = source.split("\n")[0].encode("utf-8")
    assert raw[diagnostic["column"] - 1:diagnostic["end_column"]] == b";"


def test_property_is_not_a_direct_method_call(tmp_path):
    graph = index(tmp_path, {"case.py": "class A:\n    @property\n    def value(self): return 1\ndef run():\n    instance = A()\n    return instance.value()\n"})
    assert ("case.run", "case.A.value") not in edges(graph, "call")
    assert any("Unresolved call: instance.value" in d["message"] for d in graph["diagnostics"])


def test_monkey_patch_invalidates_the_previous_method_target(tmp_path):
    graph = index(tmp_path, {"case.py": "class A:\n    def method(self): return 1\ndef run():\n    value = A()\n    value.method = 42\n    return value.method()\n"})
    assert ("case.run", "case.A.method") not in edges(graph, "call")


def test_a_function_return_value_is_not_its_nested_function_namespace(tmp_path):
    graph = index(tmp_path, {"case.py": "def factory():\n    def member(): return 1\n    return 42\ndef run():\n    return factory().member()\n"})
    assert ("case.run", "case.factory.member") not in edges(graph, "call")
    assert ("case.run", "case.factory") in edges(graph, "call")


def test_inheritance_resolution_is_independent_of_source_filename_order(tmp_path):
    graph = index(tmp_path, {"a_use.py": "from z_child import Child\ndef run():\n    value = Child()\n    return value.method()\n",
                             "z_child.py": "from zz_base import Base\nclass Child(Base): pass\n",
                             "zz_base.py": "class Base:\n    def method(self): return 1\n"})
    assert ("a_use.run", "zz_base.Base.method") in edges(graph, "call")
    assert not graph["diagnostics"]


@pytest.mark.parametrize("options", [{"source_roots": []}, {"source_roots": ["missing"]},
                                     {"source_roots": "src"}, {"python_version": "3.14"}, {"python_version": [3, 15]}])
def test_invalid_context_is_rejected_instead_of_an_empty_success(tmp_path, options):
    with pytest.raises(ValueError):
        index_project(tmp_path, options)
