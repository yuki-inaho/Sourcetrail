"""Independent graph expectations for the real, locked Clang 18 engine."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from script.indexers.cpp_indexer import capabilities, index_project
from script.indexers.graph import validate_graph

FIXTURES = Path(__file__).parent / "fixtures" / "cpp"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text())


def names(graph: dict) -> dict[str, str]:
    return {symbol["id"]: symbol["delimiter"].join(
        part if isinstance(part, str) else part["name"] for part in symbol["name"]
    ) for symbol in graph["symbols"]}


def checked(root: Path, options: dict | None = None) -> dict:
    graph = index_project(root, options)
    validate_graph(graph)
    return graph


def facts(graph: dict, expectation: dict) -> None:
    labels = names(graph)
    assert set(expectation["symbols"]) <= set(labels.values())
    calls = {(labels[e["source"]], labels[e["target"]]) for e in graph["edges"] if e["kind"] == "call"}
    assert set(map(tuple, expectation["calls"])) <= calls
    assert not graph["diagnostics"]
    assert all(f["complete"] for f in graph["files"])


def test_engine_version_and_position_contract():
    profile = capabilities()
    assert profile["engine_version"] == "18.1.8"
    assert profile["coordinate_system"] == "utf8-bytes-1-based-inclusive"
    assert not profile["partial_clearing"]


def test_unselected_source_and_header_are_observed_without_invented_symbols(tmp_path):
    (tmp_path / "main.cpp").write_text("int keep(){return 1;}\n")
    for filename in ("other.cpp", "unused.hpp"):
        (tmp_path / filename).write_text("not valid C++ in this configuration\n")
    graph = checked(tmp_path, {"files": ["main.cpp"]})
    observed = [source for source in graph["files"] if Path(source["path"]).name in {"other.cpp", "unused.hpp"}]
    assert len(observed) == 2
    assert all(source["indexed"] and not source["complete"] and not source["active"] for source in observed)
    assert set(names(graph).values()) == {"keep"}
    assert len([item for item in graph["diagnostics"] if "not parsed" in item["message"]]) == 2


def test_external_response_is_a_stored_dependency_of_the_translation_unit(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = root / "main.cpp"
    source.write_text("int selected(){return MODE;}\n")
    response = tmp_path / "flags.rsp"
    response.write_text("-DMODE=1\n")
    graph = checked(root, {"arguments": ["@" + str(response)]})
    record = next(item for item in graph["files"] if item["path"] == str(response))
    assert record["content"] == "-DMODE=1\n" and not record["indexed"]
    assert any(edge["source"] == "file:" + str(source) and edge["target"] == "file:" + str(response)
               and edge["kind"] == "include" for edge in graph["edges"])


@pytest.mark.parametrize("prefix,newline", [("", "\n"), ("\ufeff", "\r\n")])
def test_unicode_error_highlights_complete_utf8_scalars(tmp_path, prefix, newline):
    from script.indexers.graph import write_graph
    (tmp_path / "bad.cpp").write_bytes((prefix + "日本 value;" + newline).encode("utf-8"))
    graph = checked(tmp_path)
    error = next(item for item in graph["diagnostics"] if "unknown type name" in item["message"])
    assert error["column"] == (4 if prefix else 1)
    assert error["end_column"] - error["column"] == 2
    write_graph(tmp_path / "diagnostic.db", graph)


def test_modern_concepts_consteval_designators_and_generic_lambda(tmp_path):
    shutil.copy(FIXTURES / "features.cpp", tmp_path)
    graph = checked(tmp_path)
    facts(graph, EXPECTED["features"])
    labels = names(graph)
    concept = next(s for s in graph["symbols"] if labels[s["id"]] == "modern::Addable")
    assert concept["kind"] == "type" and concept["definition"] == "explicit"
    assert any(e["kind"] == "type_usage" and e["target"] == concept["id"] for e in graph["edges"])


def test_constrained_overloads_with_identical_clang_usr_remain_distinct(tmp_path):
    (tmp_path / "main.cpp").write_text(
        "template<class T> concept Small = sizeof(T) < 8;\n"
        "template<class T> concept Large = sizeof(T) >= 8;\n"
        "template<Small T> int size(T a){return 1;}\n"
        "template<Large T> int size(T a){return 2;}\n"
        "int entry(){return size(1)+size(1LL);}\n"
    )
    graph = checked(tmp_path)
    labels = names(graph)
    overloads = [s for s in graph["symbols"] if labels[s["id"]] == "size"]
    assert len(overloads) == 2
    assert len({s["name"][-1]["postfix"] for s in overloads}) == 2
    assert all(s["name"][-1]["postfix"].startswith("(T)") for s in overloads)
    calls = [e for e in graph["edges"] if e["kind"] == "call" and labels[e["source"]] == "entry"]
    assert {e["target"] for e in calls} == {s["id"] for s in overloads}
    for edge in calls:
        target = next(s for s in overloads if s["id"] == edge["target"])
        expected_column = 20 if "Small" in target["name"][-1]["postfix"] else 28
        assert edge["locations"][0]["start_column"] == expected_column


def test_explicit_template_specialization_and_ordinary_overload_remain_distinct(tmp_path):
    (tmp_path / "main.cpp").write_text(
        "template<class T> int value(T){return 1;}\n"
        "template<> int value<int>(int){return 2;}\n"
        "int value(int){return 3;}\n"
        "int entry(){return value<int>(1)+value(1.0)+value(1);}\n"
    )
    graph = checked(tmp_path)
    labels = names(graph)
    values = [s for s in graph["symbols"] if labels[s["id"]] == "value"]
    assert len(values) == 3
    calls = [e for e in graph["edges"] if e["kind"] == "call" and labels[e["source"]] == "entry"]
    assert len(calls) == 3 and {e["target"] for e in calls} == {s["id"] for s in values}
    assert any(e["kind"] == "template_specialization" for e in graph["edges"])


def test_real_coroutine_keeps_user_call_and_source_positions(tmp_path):
    shutil.copy(FIXTURES / "coroutine.cpp", tmp_path)
    graph = checked(tmp_path, {"standard": "c++20"})
    facts(graph, EXPECTED["coroutine"])
    labels = names(graph)
    call = next(e for e in graph["edges"] if e["kind"] == "call"
                and labels[e["source"]] == "execute" and labels[e["target"]] == "compute")
    assert call["locations"][0]["start_line"] == 15
    assert call["locations"][0]["start_column"] == 23


def _module_database(root: Path) -> None:
    (root / "compile_commands.json").write_text(json.dumps([
        {"directory": str(root), "file": "numbers.cppm", "arguments": ["clang++", "-std=c++23", "-x", "c++", "-c", "numbers.cppm"]},
        {"directory": str(root), "file": "main.cpp", "arguments": ["clang++", "-std=c++23", "-fmodule-file=numbers=" + str(root / "numbers.pcm"), "-c", "main.cpp"]},
    ]), encoding="utf-8")


def test_modules_exported_concept_and_real_bmi_import(tmp_path):
    for path in (FIXTURES / "modules").iterdir():
        shutil.copy(path, tmp_path)
    compiler = shutil.which("clang++")
    assert compiler, "The locked modern environment must provide clang++"
    subprocess.run([compiler, "-std=c++23", "--precompile", str(tmp_path / "numbers.cppm"), "-o", str(tmp_path / "numbers.pcm")], check=True, capture_output=True, timeout=30)
    _module_database(tmp_path)
    graph = checked(tmp_path)
    facts(graph, EXPECTED["modules"])
    dependencies = {(Path(e["source"][5:]).name, Path(e["target"][5:]).name)
                    for e in graph["edges"] if e["kind"] == "import" and e["target"].startswith("file:")}
    assert set(map(tuple, EXPECTED["modules"]["imports"])) <= dependencies


def test_invalid_bmi_is_an_execution_failure_not_a_complete_empty_graph(tmp_path):
    for path in (FIXTURES / "modules").iterdir():
        shutil.copy(path, tmp_path)
    (tmp_path / "numbers.pcm").write_bytes(b"not a Clang BMI")
    _module_database(tmp_path)
    with pytest.raises(RuntimeError, match="Clang could not parse"):
        checked(tmp_path)


def test_compilation_database_keeps_cwd_macros_and_quoted_paths(tmp_path):
    source_dir = tmp_path / "source space"
    include_dir = tmp_path / "include space"
    source_dir.mkdir()
    include_dir.mkdir()
    (include_dir / "api.hpp").write_text("int selected();\n")
    (source_dir / "main.cpp").write_text('#include "api.hpp"\n#if CHOICE == 7\nint selected(){return 7;}\n#else\nint wrong(){return 0;}\n#endif\nint main(){return selected();}\n')
    (tmp_path / "compile_commands.json").write_text(json.dumps([{
        "directory": str(source_dir), "file": "main.cpp",
        "command": 'clang++ -std=c++23 -DCHOICE=7 -I"../include space" -c main.cpp -o out.o',
    }]))
    graph = checked(tmp_path)
    assert "selected" in names(graph).values()
    assert "wrong" not in names(graph).values()
    assert not graph["diagnostics"]
    assert not (source_dir / "out.o").exists()
    assert any(Path(f["path"]).name == "api.hpp" for f in graph["files"])
    assert any(Path(f["path"]).name == "compile_commands.json" and f["language"] == "config" and f["indexed"] for f in graph["files"])


def test_conflicting_build_context_is_rejected(tmp_path):
    (tmp_path / "main.cpp").write_text("int main(){}\n")
    (tmp_path / "compile_commands.json").write_text(json.dumps([
        {"directory": str(tmp_path), "file": "main.cpp", "arguments": ["clang++", "-DMODE=" + mode, "-c", "main.cpp"]}
        for mode in ("1", "2")
    ]))
    with pytest.raises(ValueError, match="Ambiguous compilation"):
        checked(tmp_path)


@pytest.mark.parametrize("eol,bom", [("\n", False), ("\r\n", False), ("\n", True), ("\r\n", True)])
def test_unicode_positions_are_bytes_in_exact_stored_content(tmp_path, eol, bom):
    text = "int 計算() { return 3; }" + eol + "int 呼出() { return 計算(); }"
    raw = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")
    path = tmp_path / "日本語.cpp"
    path.write_bytes(raw)
    graph = checked(tmp_path)
    labels = names(graph)
    assert next(f["content"] for f in graph["files"] if f["path"] == str(path)) == raw.decode("utf-8")
    call = next(e for e in graph["edges"] if e["kind"] == "call" and labels[e["target"]] == "計算")
    location = call["locations"][0]
    assert (location["start_line"], location["start_column"], location["end_line"], location["end_column"]) == (2, 23, 2, 28)
    symbol = next(s for s in graph["symbols"] if labels[s["id"]] == "計算")
    token = next(loc for loc in symbol["locations"] if loc["kind"] == "token")
    assert token["start_column"] == 5 + (3 if bom else 0)


def test_syntax_error_is_diagnostic_and_incomplete_then_repairs(tmp_path):
    path = tmp_path / "main.cpp"
    path.write_text("int broken( {\n")
    graph = checked(tmp_path)
    assert graph["diagnostics"]
    assert not next(f["complete"] for f in graph["files"] if f["path"] == str(path))
    path.write_text("int repaired(){return 0;}\n")
    repaired = checked(tmp_path)
    assert not repaired["diagnostics"]
    assert "broken" not in names(repaired).values()
    assert "repaired" in names(repaired).values()


def test_missing_include_is_an_incomplete_graph_with_a_fatal_diagnostic(tmp_path):
    (tmp_path / "main.cpp").write_text('#include "missing.hpp"\nint main(){}\n')
    graph = checked(tmp_path)
    assert any(d["fatal"] and "missing.hpp" in d["message"] for d in graph["diagnostics"])
    assert not graph["files"][0]["complete"]


def test_inheritance_override_and_macro_provenance(tmp_path):
    (tmp_path / "main.cpp").write_text("#define CALL(x) target(x)\nint target(int v){return v;}\nstruct Base {virtual int run() const = 0;};\nstruct Derived: Base {int run() const override {return CALL(3);}};\n")
    graph = checked(tmp_path)
    labels = names(graph)
    relations = {(labels.get(e["source"], "file"), labels.get(e["target"], "file"), e["kind"]) for e in graph["edges"]}
    assert ("Derived", "Base", "inheritance") in relations
    assert ("Derived::run", "Base::run", "override") in relations
    assert ("Derived::run", "target", "call") in relations
    assert any(e["kind"] == "macro_usage" and labels[e["target"]] == "CALL" for e in graph["edges"])


def test_member_access_is_preserved_in_the_common_graph(tmp_path):
    (tmp_path / "main.cpp").write_text("class Box {\n    int hidden;\nprotected:\n    int guarded;\npublic:\n    int visible;\n};\n")
    graph = checked(tmp_path)
    labels = names(graph)
    access = {labels[s["id"]]: s.get("access") for s in graph["symbols"]}
    assert access["Box::hidden"] == "private"
    assert access["Box::guarded"] == "protected"
    assert access["Box::visible"] == "public"


def test_static_same_basename_translation_units_keep_distinct_identities(tmp_path):
    for directory in ("first", "second"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "unit.cpp").write_text("static int hidden(){return 1;}\n")
    graph = checked(tmp_path)
    hidden = [s for s in graph["symbols"] if s["name"][-1]["name"] == "hidden"]
    assert len(hidden) == 2
    assert len({s["id"] for s in hidden}) == 2
    assert len({s["name"][-1]["postfix"] for s in hidden}) == 2


def test_legacy_toy_shared_capabilities_and_exact_name_token_positions():
    root = REPOSITORY / "tests" / "toy_projects" / "fixtures" / "cxx" / "initial"
    graph = checked(root, {"standard": "c++17", "arguments": ["-Iinclude"]})
    expected = json.loads((root.parent / "expected.json").read_text())["expectations"]["initial"]
    labels = names(graph)
    symbols = {s["id"]: s for s in graph["symbols"]}
    kinds = {"function": 4096, "namespace": 16}

    def find(spec):
        if spec["kind"] == 262144:
            return "file:" + spec["name"].replace("${PROJECT_ROOT}", str(root))
        return next(key for key, s in symbols.items() if labels[key] == spec["name"]
                    and kinds.get(s["kind"]) == spec["kind"]
                    and s["name"][-1]["postfix"] == spec.get("postfix", ""))

    edge_kinds = {1: "member", 8: "call", 256: "include"}
    for spec in expected["symbols"]:
        assert find(spec)
    relations = {(e["source"], e["target"], e["kind"]) for e in graph["edges"]}
    for edge in expected["edges"]:
        assert (find(edge["source"]), find(edge["target"]), edge_kinds[edge["kind"]]) in relations
    for occurrence in expected["occurrences"]:
        symbol = symbols[find(occurrence["symbol"])]
        assert any(loc["file"] == str(root / occurrence["file"])
                   and [loc[k] for k in ("start_line", "start_column", "end_line", "end_column")] == occurrence["range"]
                   for loc in symbol["locations"])


@pytest.mark.parametrize("raw", [b"int x;\x00", b"int \xff;"])
def test_invalid_source_encoding_is_rejected(tmp_path, raw):
    (tmp_path / "bad.cpp").write_bytes(raw)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        checked(tmp_path)


def test_response_file_cycle_is_rejected(tmp_path):
    (tmp_path / "main.cpp").write_text("int x;\n")
    (tmp_path / "arguments.rsp").write_text("@arguments.rsp")
    (tmp_path / "compile_commands.json").write_text(json.dumps([{
        "directory": str(tmp_path), "file": "main.cpp", "arguments": ["clang++", "@arguments.rsp", "main.cpp"],
    }]))
    with pytest.raises(ValueError, match="Cyclic"):
        checked(tmp_path)


def test_response_file_is_an_observed_input_and_changes_the_context(tmp_path):
    (tmp_path / "main.cpp").write_text("#if MODE\nint enabled;\n#else\nint disabled;\n#endif\n")
    arguments = tmp_path / "flags.rsp"
    arguments.write_text("-std=c++23 -DMODE=1")
    graph = checked(tmp_path, {"arguments": ["@flags.rsp"]})
    assert "enabled" in names(graph).values()
    assert "disabled" not in names(graph).values()
    assert any(f["path"] == str(arguments) and f["indexed"] and f["language"] == "config" for f in graph["files"])
    arguments.write_text("-std=c++23 -DMODE=0")
    changed = checked(tmp_path, {"arguments": ["@flags.rsp"]})
    assert "disabled" in names(changed).values()
    assert "enabled" not in names(changed).values()


def test_plugin_arguments_are_explicitly_rejected(tmp_path):
    (tmp_path / "main.cpp").write_text("int x;")
    with pytest.raises(ValueError, match="Compiler plugins"):
        checked(tmp_path, {"arguments": ["-Xclang", "-load", "unknown.so"]})


def test_no_source_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="No C/C++"):
        checked(tmp_path)


def test_last_translation_unit_deletion_with_explicit_empty_database(tmp_path):
    database = tmp_path / "compile_commands.json"
    source = tmp_path / "main.cpp"
    source.write_text("int removed(){return 7;}\n")
    database.write_text(json.dumps([{"directory": str(tmp_path), "file": "main.cpp", "arguments": ["clang++", "-c", "main.cpp"]}]))
    assert "removed" in names(checked(tmp_path)).values()
    source.unlink()
    database.write_text("[]\n")
    graph = checked(tmp_path)
    assert not graph["symbols"] and not graph["edges"] and not graph["diagnostics"]
    assert graph["files"] == [{"path": str(database), "content": "[]\n", "language": "config", "indexed": True, "complete": True}]


def test_empty_database_does_not_hide_existing_sources(tmp_path):
    (tmp_path / "compile_commands.json").write_text("[]")
    (tmp_path / "existing.cpp").write_text("int x;")
    with pytest.raises(ValueError, match="No C/C++"):
        checked(tmp_path)


def test_stale_database_with_missing_source_is_rejected(tmp_path):
    (tmp_path / "compile_commands.json").write_text(json.dumps([{
        "directory": str(tmp_path), "file": "deleted.cpp", "arguments": ["clang++", "-c", "deleted.cpp"],
    }]))
    with pytest.raises(FileNotFoundError):
        checked(tmp_path)
