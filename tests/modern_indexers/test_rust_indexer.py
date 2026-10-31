"""Independent Rust expectations, real engine integration and failure controls."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from script.indexers.graph import GraphError, validate_graph
from script.indexers.rust_indexer import (
    RustIndexError, Source, capabilities, index_project,
)
from script.indexers.rust_lsp import RustLanguageServer, RustProtocolError
from script.indexers import rust_runtime


FIXTURE = Path(__file__).parent / "fixtures/rust"
EXPECTED = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))


def _name(symbol: dict) -> str:
    return "::".join(part if isinstance(part, str) else part["name"] for part in symbol["name"])


def _relations(graph: dict, kind: str) -> set[tuple[str, str]]:
    names = {symbol["id"]: _name(symbol) for symbol in graph["symbols"]}
    return {(names.get(edge["source"], edge["source"]), names.get(edge["target"], edge["target"]))
            for edge in graph["edges"] if edge["kind"] == kind}


def _copy(destination: Path) -> Path:
    shutil.copytree(FIXTURE, destination)
    return destination


@pytest.fixture(scope="module")
def indexed_workspace(tmp_path_factory):
    root = _copy(tmp_path_factory.mktemp("rust") / "workspace")
    lock_contents = (root / "Cargo.lock").read_bytes()
    graph = index_project(root)
    validate_graph(graph)
    assert (root / "Cargo.lock").read_bytes() == lock_contents
    return root, graph


def test_rust_capabilities_negotiate_coordinate_and_database_contract():
    profile = capabilities()
    assert profile["protocol_version"] == 1
    assert profile["database_version"] == 25
    assert profile["coordinate_unit"] == "utf8-byte"
    assert "2024" in profile["editions"]
    assert profile["partial_clearing"] is False


def test_real_workspace_definitions_match_independent_expectations(indexed_workspace):
    _, graph = indexed_workspace
    names = {_name(symbol) for symbol in graph["symbols"] if symbol["definition"] == "explicit"}
    assert set(EXPECTED["definitions"]) <= names
    assert "shapes::optional" not in names
    assert "shapes::configured" not in names
    assert "shapes::test_only" not in names
    assert all(source["complete"] for source in graph["files"])
    assert not [diagnostic for diagnostic in graph["diagnostics"] if diagnostic.get("severity") != "warning"]


@pytest.mark.parametrize(("expected", "kind"), [
    ("calls", "call"), ("trait_implementations", "inheritance"),
    ("method_implementations", "override"), ("macro_uses", "macro_usage"),
])
def test_rust_semantic_relations(indexed_workspace, expected, kind):
    _, graph = indexed_workspace
    assert {tuple(pair) for pair in EXPECTED[expected]} <= _relations(graph, kind)


def test_rust_calls_are_not_guessed_by_unqualified_name(indexed_workspace):
    _, graph = indexed_workspace
    calls = _relations(graph, "call")
    assert ("shape_app::run", "shapes::Measure::measure") not in calls
    assert ("shape_app::run", "shapes::impl Measure for Square::measure") in calls
    assert not any(source == target for source, target in _relations(graph, "override"))
    symbols = {_name(symbol): symbol for symbol in graph["symbols"]}
    assert symbols["shapes::Square"]["access"] == "public"
    assert symbols["shape_app::run"]["access"] == "private"


def test_rust_unicode_token_is_exact_utf8_span(indexed_workspace):
    _, graph = indexed_workspace
    symbol = next(symbol for symbol in graph["symbols"] if _name(symbol) == "shapes::計算")
    location = next(location for location in symbol["locations"] if location["kind"] == "token")
    source = next(source for source in graph["files"] if source["path"] == location["file"])
    line = source["content"].split("\n")[location["start_line"] - 1].encode("utf-8")
    assert line[location["start_column"] - 1:location["end_column"]].decode("utf-8") == "計算"
    assert location["end_column"] - location["start_column"] + 1 == 6


def test_rust_cross_crate_dependencies_and_configuration_inputs(indexed_workspace):
    root, graph = indexed_workspace
    dependencies = _relations(graph, "import")
    assert ("file:" + str(root / "app/src/main.rs"),
            "file:" + str(root / "shapes/src/lib.rs")) in dependencies
    assert ("file:" + str(root / "shapes/src/lib.rs"),
            "file:" + str(root / "shapes/src/operations.rs")) in dependencies
    paths = {Path(source["path"]).relative_to(root).as_posix(): source for source in graph["files"]}
    for path in ("Cargo.toml", "Cargo.lock", "app/Cargo.toml", "shapes/Cargo.toml"):
        assert paths[path]["language"] == "config"
        assert paths[path]["indexed"]


def test_rust_standard_library_call_is_resolved_without_invented_source(indexed_workspace):
    _, graph = indexed_workspace
    names = {symbol["id"]: _name(symbol) for symbol in graph["symbols"]}
    targets = {edge["target"] for edge in graph["edges"] if edge["kind"] == "call"
               and names[edge["source"]] == "shapes::machine_width"}
    matching = [symbol for symbol in graph["symbols"] if symbol["id"] in targets
                and _name(symbol).endswith("::size_of")]
    assert matching
    assert all(symbol["definition"] == "none" and symbol["locations"] == [] for symbol in matching)


def test_rust_feature_selection_changes_active_symbols_and_identity(tmp_path):
    root = _copy(tmp_path / "workspace")
    graph = index_project(root, {"features": ["shapes/extra"], "cfg": ["custom_mode"], "all_targets": True})
    validate_graph(graph)
    assert "shapes::optional" in {_name(symbol) for symbol in graph["symbols"]}
    assert "shapes::configured" in {_name(symbol) for symbol in graph["symbols"]}
    assert "shapes::test_only" in {_name(symbol) for symbol in graph["symbols"]}
    assert graph["context"]["features"] == ["shapes/extra"]
    default = index_project(root)
    assert graph["context"]["configuration"] != default["context"]["configuration"]
    feature_symbol = next(symbol for symbol in graph["symbols"] if _name(symbol) == "shapes::Square")
    default_symbol = next(symbol for symbol in default["symbols"] if _name(symbol) == "shapes::Square")
    assert feature_symbol["id"] != default_symbol["id"]
    assert feature_symbol["name"] != default_symbol["name"]


def test_rust_observes_inactive_and_configuration_files_for_native_refresh(tmp_path):
    root = _copy(tmp_path / "workspace")
    (root / "orphan.rs").write_text("pub fn not_in_crate() { missing(); }\n", encoding="utf-8")
    (root / ".hidden.rs").write_text("pub fn hidden_not_in_crate() {}\n", encoding="utf-8")
    (root / "settings.toml").write_text("answer = 42\n", encoding="utf-8")
    for directory in ("target", ".git", ".pixi", ".venv", "venv", "__pycache__"):
        excluded = root / directory
        excluded.mkdir(exist_ok=True)
        (excluded / "excluded.rs").write_text("this is deliberately invalid Rust", encoding="utf-8")
    graph = index_project(root)
    validate_graph(graph)
    paths = {Path(source["path"]).relative_to(root).as_posix(): source for source in graph["files"]}
    for path in ("orphan.rs", ".hidden.rs", "settings.toml"):
        assert paths[path]["indexed"]
        assert paths[path]["complete"]
        assert paths[path]["content"].encode("utf-8") == (root / path).read_bytes()
    assert set(graph["context"]["inactive_inputs"]) == {"orphan.rs", ".hidden.rs"}
    assert not paths["orphan.rs"]["active"]
    assert not any(path.endswith("excluded.rs") for path in paths)
    assert not any("not_in_crate" in _name(symbol) for symbol in graph["symbols"])
    repeated = index_project(root)
    assert graph == repeated


@pytest.mark.parametrize("config_name", ["config", "config.toml"])
def test_rust_target_option_environment_and_workspace_config_agree(tmp_path, monkeypatch, config_name):
    root = _copy(tmp_path / "workspace")
    target = "x86_64-unknown-linux-gnu"
    (root / ".cargo").mkdir()
    config_path = root / ".cargo" / config_name
    config_path.write_text(f'[build]\ntarget = "{target}"\n', encoding="utf-8")
    configured = index_project(root)
    validate_graph(configured)
    assert configured["context"]["target"] == target
    assert str(config_path) in {source["path"] for source in configured["files"]}
    explicit = index_project(root, {"target": target})
    assert configured == explicit
    monkeypatch.setenv("CARGO_BUILD_TARGET", target)
    from_environment = index_project(root)
    assert configured == from_environment


def test_rust_compiler_error_is_diagnostic_and_incomplete(tmp_path):
    root = _copy(tmp_path / "workspace")
    source = root / "shapes/src/operations.rs"
    source.write_text('pub fn double(value: i32) -> i32 { missing(value) }\n', encoding="utf-8")
    graph = index_project(root)
    validate_graph(graph)
    assert any("missing" in diagnostic["message"] for diagnostic in graph["diagnostics"])
    assert not any(item["complete"] for item in graph["files"])
    assert not any("missing" in _name(symbol) and symbol["definition"] == "explicit"
                   for symbol in graph["symbols"])


def test_rust_change_and_delete_equal_clean_rebuild(tmp_path):
    root = _copy(tmp_path / "workspace")
    first = index_project(root)
    assert "shapes::operations::double" in {_name(symbol) for symbol in first["symbols"]}
    (root / "shapes/src/operations.rs").unlink()
    (root / "shapes/src/lib.rs").write_text('pub fn replacement() -> i32 { 13 }\n', encoding="utf-8")
    (root / "app/src/main.rs").write_text('fn main() { let _value = shapes::replacement(); }\n', encoding="utf-8")
    updated = index_project(root)
    validate_graph(updated)
    clean_root = tmp_path / "clean"
    shutil.copytree(root, clean_root, ignore=shutil.ignore_patterns("target"))
    rebuilt = index_project(clean_root)
    validate_graph(rebuilt)
    normalize = lambda graph, path: json.dumps(graph, sort_keys=True, ensure_ascii=False).replace(str(path), "<workspace>")
    assert normalize(updated, root) == normalize(rebuilt, clean_root)
    assert not any("operations" in _name(symbol) for symbol in updated["symbols"])
    assert not any(source["path"].endswith("operations.rs") for source in updated["files"])


def test_rust_bom_crlf_and_no_final_newline(tmp_path):
    root = _copy(tmp_path / "workspace")
    for source in root.rglob("*.rs"):
        text = source.read_bytes().decode("utf-8").rstrip("\n").replace("\n", "\r\n")
        source.write_bytes(("\ufeff" + text).encode("utf-8"))
    graph = index_project(root)
    validate_graph(graph)
    assert set(EXPECTED["definitions"]) <= {_name(symbol) for symbol in graph["symbols"]}
    for source in graph["files"]:
        assert source["content"].encode("utf-8") == Path(source["path"]).read_bytes()


@pytest.mark.parametrize("options", [
    {"features": "extra"}, {"features": [""]},
    {"features": ["extra"], "all_features": True}, {"proc_macros": True},
    {"timeout": 0}, {"timeout": 3601},
    {"cfg": "custom_mode"}, {"cfg": [""]},
    {"all_features": "false"},
])
def test_rust_rejects_unsupported_or_invalid_configuration(tmp_path, options):
    root = _copy(tmp_path / "workspace")
    with pytest.raises(RustIndexError):
        index_project(root, options)


def test_rust_missing_manifest_is_not_empty_success(tmp_path):
    with pytest.raises(RustIndexError, match="Cargo.toml"):
        index_project(tmp_path)


def test_rust_corrupt_coordinate_negative_control(indexed_workspace):
    _, original = indexed_workspace
    graph = copy.deepcopy(original)
    symbol = next(symbol for symbol in graph["symbols"] if _name(symbol) == "shapes::計算")
    symbol["locations"][0]["end_column"] -= 1
    with pytest.raises(GraphError, match="UTF-8"):
        validate_graph(graph)


def test_rust_half_open_range_conversion_does_not_include_crlf(tmp_path):
    source = Source(tmp_path / "code.rs", "fn 計算() {}\r\n")
    token = source.location({"start": {"line": 0, "character": 3},
                             "end": {"line": 0, "character": 9}})
    assert token["start_column"] == 4
    assert token["end_column"] == 9
    scope = source.location({"start": {"line": 0, "character": 0},
                             "end": {"line": 1, "character": 0}}, "scope")
    assert scope["end_line"] == 1
    assert scope["end_column"] == len("fn 計算() {}".encode("utf-8"))
    with pytest.raises(RustProtocolError, match="line"):
        source.location({"start": {"line": 4, "character": 0},
                         "end": {"line": 4, "character": 1}})


@pytest.mark.parametrize(("behavior", "message"), [
    ("bad_length", "message size"), ("utf16", "UTF-8"), ("silent", "timed out"),
])
def test_rust_protocol_failure_reaps_real_engine_process(tmp_path, behavior, message):
    executable = tmp_path / "broken-engine"
    pid_file = tmp_path / "engine.pid"
    body = (
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
    )
    if behavior == "bad_length":
        body += "sys.stdout.buffer.write(b'Content-Length: -1\\r\\n\\r\\n'); sys.stdout.buffer.flush()\n"
    elif behavior == "utf16":
        body += (
            "value=json.dumps({'jsonrpc':'2.0','id':1,'result':{'capabilities':{'positionEncoding':'utf-16'}}}).encode()\n"
            "sys.stdout.buffer.write(('Content-Length: %d\\r\\n\\r\\n'%len(value)).encode()+value); sys.stdout.buffer.flush()\n"
        )
    body += "sys.stdin.buffer.read()\n"
    executable.write_text(body, encoding="utf-8")
    executable.chmod(0o755)
    with pytest.raises(RustProtocolError, match=message):
        RustLanguageServer(executable, tmp_path, os.environ.copy(), {}, timeout=1)
    process_id = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(process_id, 0)


def test_rust_runtime_failed_download_preserves_existing_installation(tmp_path, monkeypatch):
    destination = tmp_path / "runtime"
    destination.mkdir()
    (destination / "rust-analyzer").write_bytes(b"previous-engine")

    def failing_download(*_arguments):
        raise RuntimeError("injected checksum failure")

    monkeypatch.setattr(rust_runtime, "_download", failing_download)
    with pytest.raises(RuntimeError, match="checksum failure"):
        rust_runtime.prepare(destination)
    assert (destination / "rust-analyzer").read_bytes() == b"previous-engine"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["runtime"]
