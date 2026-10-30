"""Regression coverage of the production Python parser and database writer."""

import pytest

from support import EDGE_INHERITANCE, NODE_CLASS, NODE_FUNCTION


pytestmark = pytest.mark.regression


def test_function_definitions_calls_and_source_locations(python_indexer):
    graph = python_indexer.index(
        "def increment(value):\n"
        "    return value + 1\n"
        "\n"
        "def caller():\n"
        "    return increment(41)\n"
    )

    assert not graph.errors
    assert graph.definitions["sample.increment"] == NODE_FUNCTION
    assert graph.definitions["sample.caller"] == NODE_FUNCTION
    assert graph.targets("sample.caller") == {"sample.increment"}
    assert 1 in graph.definition_lines["sample.increment"]
    assert 4 in graph.definition_lines["sample.caller"]
    assert graph.files == {python_indexer.work_directory / "sample.py"}


def test_class_inheritance_and_same_named_methods_remain_distinct(python_indexer):
    graph = python_indexer.index(
        "class Parent:\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "class Child(Parent):\n"
        "    def run(self):\n"
        "        return 2\n"
        "\n"
        "class Unrelated:\n"
        "    def run(self):\n"
        "        return 3\n"
    )

    assert not graph.errors
    for name in ("Parent", "Child", "Unrelated"):
        assert graph.definitions[f"sample.{name}"] == NODE_CLASS
        # The Python indexer records methods as functions in schema 25.
        assert graph.definitions[f"sample.{name}.run"] == NODE_FUNCTION
    assert graph.targets("sample.Child", EDGE_INHERITANCE) == {"sample.Parent"}
    assert not graph.targets("sample.Unrelated", EDGE_INHERITANCE)


def test_utf8_source_and_unicode_file_path(python_indexer):
    graph = python_indexer.index(
        "# -*- coding: utf-8 -*-\n"
        "# 日本語のソースとパスを解析します。\n"
        "def greeting():\n"
        "    return 'こんにちは'\n",
        filename="挨拶.py",
    )

    assert not graph.errors
    assert graph.definitions["挨拶.greeting"] == NODE_FUNCTION
    assert 3 in graph.definition_lines["挨拶.greeting"]
    assert graph.files == {python_indexer.work_directory / "挨拶.py"}


def test_syntax_error_is_persisted_in_index(python_indexer):
    graph = python_indexer.index("def broken()\n    pass\n")

    assert graph.errors, "A syntax error must be visible to Sourcetrail users."
    assert any("Unexpected token" in message for message in graph.errors), graph.errors
