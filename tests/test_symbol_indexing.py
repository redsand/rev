#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for symbol indexing."""

import pytest
import tempfile
from pathlib import Path

from rev.retrieval.symbol_index import Symbol, SymbolIndexer, SymbolVisitor


class TestSymbolIndexer:
    """Test symbol indexing functionality."""

    def test_parse_simple_function(self):
        """Verify parsing a simple function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test file
            test_file = tmpdir / "test.py"
            test_file.write_text('''
def hello():
    """Say hello."""
    print("Hello")
''')

            # Parse file
            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            # Check symbols
            symbols = indexer.find_symbol("hello")
            assert len(symbols) == 1
            assert symbols[0].kind == "function"
            assert symbols[0].name == "hello"
            assert symbols[0].docstring == "Say hello."

    def test_parse_class_with_methods(self):
        """Verify parsing classes and methods."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
class Calculator:
    """A simple calculator."""

    def add(self, a, b):
        """Add two numbers."""
        return a + b

    def subtract(self, a, b):
        return a - b
''')

            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            # Check class
            classes = indexer.find_symbol("Calculator", kind="class")
            assert len(classes) == 1
            assert classes[0].docstring == "A simple calculator."

            # Check methods
            add_methods = indexer.find_symbol("add")
            assert len(add_methods) == 1
            assert add_methods[0].kind == "method"
            assert add_methods[0].parent == "Calculator"

    def test_parse_module_variables(self):
        """Verify parsing module-level variables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
VERSION = "1.0.0"
DEBUG = False

class MyClass:
    CLASS_VAR = 42
''')

            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            # Check module variables
            version_var = indexer.find_symbol("VERSION")
            assert len(version_var) == 1
            assert version_var[0].kind == "variable"

            # Check class variables
            class_var = indexer.find_symbol("CLASS_VAR")
            assert len(class_var) == 1
            assert class_var[0].parent == "MyClass"

    def test_search_symbols(self):
        """Verify symbol search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
def test_function():
    pass

def test_another():
    pass

def helper():
    pass
''')

            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            # Search for "test" should return both test functions
            results = indexer.search_symbols("test")
            assert len(results) == 2
            assert all(s.name.startswith("test_") for s in results)

    def test_get_stats(self):
        """Verify statistics collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
VERSION = "1.0"

class MyClass:
    def method1(self):
        pass

    def method2(self):
        pass

def function1():
    pass
''')

            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            stats = indexer.get_stats()
            assert stats["files"] == 1
            assert stats["classes"] == 1
            assert stats["methods"] == 2
            assert stats["functions"] == 1
            assert stats["variables"] == 1

    def test_find_by_kind(self):
        """Verify finding symbols by kind."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
class A:
    pass

class B:
    pass

def func():
    pass
''')

            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            classes = indexer.find_by_kind("class")
            assert len(classes) == 2

            functions = indexer.find_by_kind("function")
            assert len(functions) == 1

    def test_find_in_file(self):
        """Verify finding all symbols in a file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
class A:
    def method(self):
        pass

def func():
    pass

VAR = 1
''')

            indexer = SymbolIndexer(tmpdir)
            indexer.build_index()

            symbols = indexer.find_in_file(test_file)
            assert len(symbols) == 4  # class, method, function, variable


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
