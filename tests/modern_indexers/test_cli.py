"""Adapter configuration must reject malformed inputs before creating artifacts."""

import json
import xml.etree.ElementTree as ET

import pytest

from script.indexers.cli import configure_project, read_config
from script.indexers.graph import GraphError


@pytest.mark.parametrize("field,value", [("language", []), ("language", {}), ("language", 1),
                                          ("options", []), ("options", False), ("root", ""),
                                          ("root", "bad\x00path"), ("root", 1), ("protocol_version", True)])
def test_read_config_rejects_invalid_field_types(tmp_path, field, value):
    configuration = tmp_path / "project.srctrlcfg"
    data = {"protocol_version": 1, "language": "python", "root": ".", "options": {}}
    data[field] = value
    configuration.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GraphError):
        read_config(configuration)


@pytest.mark.parametrize("suffix", [".srctrlcfg", ".srctrldb", ".xml", ""])
def test_configure_requires_a_project_suffix_and_cannot_overwrite_its_config(tmp_path, suffix):
    project = tmp_path / ("project" + suffix)
    with pytest.raises(GraphError, match="srctrlprj"):
        configure_project("python", tmp_path, project)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("options", [False, [], 1, "bad", {"source_roots": "src"},
                                      {"source_roots": []}, {"source_roots": [1]},
                                      {"source_roots": ["missing"]}])
def test_configure_validates_options_used_to_enumerate_sources(tmp_path, options):
    with pytest.raises(GraphError):
        configure_project("python", tmp_path, tmp_path / "project.srctrlprj", options=options)
    assert list(tmp_path.iterdir()) == []


def test_configure_python_excludes_the_same_build_directory_as_the_adapter(tmp_path):
    project, configuration = configure_project("python", tmp_path, tmp_path / "project.srctrlprj")
    assert read_config(configuration)["options"] == {}
    group = ET.parse(project).getroot().find("source_groups")[0]
    filters = {node.text for node in group.find("exclude_filters")}
    assert {str(tmp_path / "build/**"), str(tmp_path / "**/build/**")} <= filters
    assert all(value.startswith(str(tmp_path) + "/") for value in filters)


def test_configure_rejects_non_path_compilation_database(tmp_path):
    with pytest.raises(GraphError):
        configure_project("cpp", tmp_path, tmp_path / "project.srctrlprj", options={"compilation_database": []})
    assert list(tmp_path.iterdir()) == []


def test_cpp_native_extensions_cover_the_engine_discovery_profile(tmp_path):
    from script.indexers.cpp_indexer import HEADER_SUFFIXES, SOURCE_SUFFIXES
    project, _ = configure_project("cpp", tmp_path, tmp_path / "project.srctrlprj")
    group = ET.parse(project).getroot().find("source_groups")[0]
    assert {node.text for node in group.find("source_extensions")} == SOURCE_SUFFIXES | HEADER_SUFFIXES


def test_missing_extensionless_rust_configurations_are_registered_for_later_creation(tmp_path):
    project, _ = configure_project("rust", tmp_path, tmp_path / "project.srctrlprj")
    group = ET.parse(project).getroot().find("source_groups")[0]
    paths = {node.text for node in group.find("source_paths")}
    assert {str(tmp_path / ".cargo/config"), str(tmp_path / "rust-toolchain")} <= paths
