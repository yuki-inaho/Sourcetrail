#!/usr/bin/env python3
"""Configure and run versioned project-wide language adapters."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from script.indexers.graph import DATABASE_VERSION, PROTOCOL_VERSION, GraphError, graph_json, validate_graph, write_graph


ENGINES = {"python": "python_indexer", "cpp": "cpp_indexer", "rust": "rust_indexer"}
EXTENSIONS = {"python": [".py"], "cpp": [".c", ".cc", ".cpp", ".cxx", ".c++", ".C", ".cppm", ".ixx", ".mpp",
                                        ".h", ".hh", ".hpp", ".hxx", ".inc", ".inl"],
              "rust": [".rs", ".toml", ".lock"]}


def engine(language: str):
    if not isinstance(language, str) or language not in ENGINES:
        raise GraphError(f"Unsupported adapter language: {language!r}")
    return importlib.import_module("script.indexers." + ENGINES[language])


def read_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"protocol_version", "language", "root", "options"}:
        raise GraphError("Adapter configuration requires protocol_version, language, root and options")
    if type(data["protocol_version"]) is not int or data["protocol_version"] != PROTOCOL_VERSION:
        raise GraphError(f"Unsupported adapter protocol: {data['protocol_version']!r}")
    if not isinstance(data["language"], str) or data["language"] not in ENGINES or not isinstance(data["options"], dict):
        raise GraphError("Invalid adapter language/options")
    if not isinstance(data["root"], str) or not data["root"] or "\x00" in data["root"]:
        raise GraphError("Invalid project root")
    data["root"] = str((path.parent / data["root"]).resolve())
    if not Path(data["root"]).is_dir():
        raise GraphError(f"Project root does not exist: {data['root']}")
    return data


def configure_project(language: str, root: Path, project: Path, *, options: dict | None = None) -> tuple[Path, Path]:
    """Create a native project-wide source group with explicit interpreter/engine configuration."""
    root, project = root.resolve(), project.resolve()
    if not isinstance(language, str) or language not in ENGINES or not root.is_dir():
        raise GraphError("A supported language and existing source directory are required")
    if project.suffix != ".srctrlprj":
        raise GraphError("A project filename must end in .srctrlprj")
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise GraphError("Engine options must be a JSON object")
    source_roots = options.get("source_roots", ["."]) if language == "python" else ["."]
    if (not isinstance(source_roots, list) or not source_roots
            or any(not isinstance(value, str) or not value or "\x00" in value for value in source_roots)):
        raise GraphError("Python source_roots must be a nonempty list of directories")
    if any(not (root / value).is_dir() for value in source_roots):
        raise GraphError("A configured source root does not exist")
    compilation_database = options.get("compilation_database", "compile_commands.json")
    if language == "cpp" and (not isinstance(compilation_database, str) or not compilation_database or "\x00" in compilation_database):
        raise GraphError("compilation_database must be a nonempty path string")
    configuration = project.with_suffix(".srctrlcfg")
    if project.exists() or configuration.exists():
        raise GraphError("Refusing to overwrite an existing project or adapter configuration")
    project.parent.mkdir(parents=True, exist_ok=True)
    data = {"protocol_version": PROTOCOL_VERSION, "language": language,
            "root": os.path.relpath(root, configuration.parent), "options": options}
    config = ET.Element("config")
    ET.SubElement(config, "version").text = "8"
    groups = ET.SubElement(config, "source_groups")
    group = ET.SubElement(groups, "source_group_modern_" + language)
    ET.SubElement(group, "type").text = "Modern Language Source Group"
    ET.SubElement(group, "name").text = {"python": "Python 3.14", "cpp": "C++20 / C++23 (Clang 18)", "rust": "Rust (Cargo / rust-analyzer)"}[language]
    ET.SubElement(group, "status").text = "enabled"
    ET.SubElement(group, "run_in_parallel").text = "0"
    paths = ET.SubElement(group, "source_paths")
    for value in source_roots:
        ET.SubElement(paths, "source_path").text = str((root / value).resolve())
    ET.SubElement(paths, "source_path").text = str(configuration)
    if language == "cpp":
        compilation_database = (root / compilation_database).resolve()
        if compilation_database.is_dir():
            compilation_database /= "compile_commands.json"
        ET.SubElement(paths, "source_path").text = str(compilation_database)
    elif language == "rust":
        for filename in ("Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml", ".cargo/config", ".cargo/config.toml"):
            # Missing explicit paths become observable when created later,
            # including extensionless Cargo/toolchain configuration files.
            ET.SubElement(paths, "source_path").text = str(root / filename)
    extensions = ET.SubElement(group, "source_extensions")
    for extension in EXTENSIONS[language]:
        ET.SubElement(extensions, "source_extension").text = extension
    excludes = ET.SubElement(group, "exclude_filters")
    folders = [".git", ".pixi", ".venv", "venv", "target", "__pycache__"]
    if language == "python":
        folders.append("build")
    for value in source_roots:
        source_root = (root / value).resolve()
        for folder in folders:
            # Native filters match the entire absolute path. Scope each one
            # below this root, so /tmp/build/project remains a valid root.
            for suffix in (folder + "/**", "**/" + folder + "/**"):
                ET.SubElement(excludes, "exclude_filter").text = str(source_root / suffix)
    # The native group runs once for the selected project and still observes every input file.
    # The source argument is retained for ordinary command-template validation and receipts.
    arguments = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), "index",
                 "--config", str(configuration), "--database", "%{DATABASE_FILE_PATH}",
                 "--database-version", "%{DATABASE_VERSION}", "--source", "%{SOURCE_FILE_PATH}"]
    if any('"' in arg or "\n" in arg or "\r" in arg for arg in arguments):
        raise GraphError("Project paths containing quotes/newlines cannot be represented by this command template")
    ET.SubElement(group, "custom_command").text = " ".join('"' + arg + '"' for arg in arguments)
    configuration.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ET.indent(config)
    ET.ElementTree(config).write(project, encoding="utf-8", xml_declaration=True)
    return project, configuration


def index(configuration: Path, database: Path, database_version: int, *, graph_output: Path | None = None) -> dict:
    configuration = configuration.resolve()
    original_config = configuration.read_bytes()
    config = read_config(configuration)
    if type(database_version) is not int or database_version != DATABASE_VERSION:
        raise GraphError(f"Unsupported requested database version: {database_version}")
    # The locked environment must reach child tools even when launched from the GUI.
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    adapter = engine(config["language"])
    capabilities = adapter.capabilities()
    if not isinstance(capabilities, dict):
        raise GraphError("Adapter capabilities must be an object")
    for field, expected in (("protocol_version", PROTOCOL_VERSION), ("database_version", DATABASE_VERSION),
                            ("coordinate_unit", "utf8-byte")):
        if type(capabilities.get(field)) is not type(expected) or capabilities[field] != expected:
            raise GraphError(f"Adapter capability mismatch: {field}={capabilities.get(field)!r}")
    graph = adapter.index_project(Path(config["root"]), config["options"])
    validate_graph(graph)
    # A configuration is an indexed input, including when all source files were deleted.
    if not any(source["path"] == str(configuration) for source in graph["files"]):
        graph["files"].append({"path": str(configuration), "content": original_config.decode("utf-8"),
                               "language": "config", "indexed": True, "complete": True})
    # Refuse an observed source that changed while the engine was analysing it.
    # This guards individual inputs; it is not an atomic filesystem snapshot.
    digests = {}
    for source in graph["files"]:
        path = Path(source["path"])
        if source.get("indexed", True):
            raw = path.read_bytes()
            if raw.decode("utf-8") != source["content"]:
                raise GraphError(f"Input changed during analysis: {path}")
            digests[str(path)] = hashlib.sha256(raw).hexdigest()
    if graph_output is not None:
        graph_output.parent.mkdir(parents=True, exist_ok=True)
        graph_output.write_text(graph_json(graph), encoding="utf-8")
    result = write_graph(database, graph, expected_version=database_version)
    return {"protocol_version": PROTOCOL_VERSION, "capabilities": capabilities,
            "counts": result, "source_sha256": digests}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure", help="Create a Sourcetrail project for a modern source adapter")
    configure.add_argument("--language", choices=ENGINES, required=True)
    configure.add_argument("--root", type=Path, required=True)
    configure.add_argument("--project", type=Path, required=True)
    configure.add_argument("--options", type=Path, help="JSON object containing explicit engine options")
    capability = commands.add_parser("capabilities")
    capability.add_argument("--language", choices=ENGINES, required=True)
    run = commands.add_parser("index")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--database", type=Path, required=True)
    run.add_argument("--database-version", type=int, default=DATABASE_VERSION)
    run.add_argument("--source", type=Path, help="Native group trigger; the group is indexed as a whole")
    run.add_argument("--graph-output", type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.command == "configure":
            options = json.loads(args.options.read_text(encoding="utf-8")) if args.options else {}
            if not isinstance(options, dict):
                raise GraphError("Engine options must be a JSON object")
            project, configuration = configure_project(args.language, args.root, args.project, options=options)
            print(json.dumps({"project": str(project), "configuration": str(configuration)}, ensure_ascii=False))
        elif args.command == "capabilities":
            print(json.dumps(engine(args.language).capabilities(), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(index(args.config, args.database, args.database_version, graph_output=args.graph_output),
                             ensure_ascii=False, sort_keys=True))
    except (GraphError, ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as error:
        print(f"Sourcetrail adapter rejected output: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
