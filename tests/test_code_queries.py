#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for code query engine."""

import pytest
import tempfile
from pathlib import Path

from rev.retrieval.symbol_index import SymbolIndexer
from rev.retrieval.import_graph import ImportGraph
from rev.retrieval.code_queries import CodeQueryEngine


class TestCodeQueryEngine:
    """Test code query engine functionality."""

    def test_find_callers(self):
        """Verify finding function callers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create module with function
            module = tmpdir / "module.py"
            module.write_text('''
def target_function():
    pass
''')

            # Create caller file
            caller = tmpdir / "caller.py"
            caller.write_text('''
from module import target_function

def caller1():
    target_function()

def caller2():
    result = target_function()
''')

            # Build indices
            symbol_index = SymbolIndexer(tmpdir)
            symbol_index.build_index()

            import_graph = ImportGraph(tmpdir)
            import_graph.build_graph()

            # Query
            engine = CodeQueryEngine(symbol_index, import_graph)
            callers = engine.find_callers("target_function")

            # Should find two call sites
            assert len(callers) >= 2

    def test_find_implementers(self):
        """Verify finding class implementers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
class BaseClass:
    pass

class Impl1(BaseClass):
    pass

class Impl2(BaseClass):
    pass

class Unrelated:
    pass
''')

            # Build indices
            symbol_index = SymbolIndexer(tmpdir)
            symbol_index.build_index()

            import_graph = ImportGraph(tmpdir)
            import_graph.build_graph()

            # Query
            engine = CodeQueryEngine(symbol_index, import_graph)
            implementers = engine.find_implementers("BaseClass")

            # Should find two implementers
            assert len(implementers) == 2
            impl_names = [s.name for s in implementers]
            assert "Impl1" in impl_names
            assert "Impl2" in impl_names
            assert "Unrelated" not in impl_names

    def test_find_usages(self):
        """Verify finding symbol usages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
MY_CONSTANT = 42

def func1():
    x = MY_CONSTANT

def func2():
    y = MY_CONSTANT + 1

class MyClass:
    value = MY_CONSTANT
''')

            # Build indices
            symbol_index = SymbolIndexer(tmpdir)
            symbol_index.build_index()

            import_graph = ImportGraph(tmpdir)
            import_graph.build_graph()

            # Query
            engine = CodeQueryEngine(symbol_index, import_graph)
            usages = engine.find_usages("MY_CONSTANT")

            # Should find multiple usages
            assert len(usages) >= 3  # Definition + 3 usages

    def test_find_related_symbols(self):
        """Verify finding related symbols."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create main module
            main = tmpdir / "main.py"
            main.write_text('''
from helper import util_func

def main_func():
    util_func()

class MainClass:
    pass
''')

            # Create helper module
            helper = tmpdir / "helper.py"
            helper.write_text('''
def util_func():
    pass

def helper_func():
    pass
''')

            # Build indices
            symbol_index = SymbolIndexer(tmpdir)
            symbol_index.build_index()

            import_graph = ImportGraph(tmpdir)
            import_graph.build_graph()

            # Query
            engine = CodeQueryEngine(symbol_index, import_graph)

            # Get main_func symbol
            main_funcs = symbol_index.find_symbol("main_func")
            assert len(main_funcs) == 1

            # Find related symbols
            related = engine.find_related_symbols(main_funcs[0])

            # Should include symbols from same file and imported files
            assert len(related) > 0
            related_names = [s.name for s in related]
            assert "MainClass" in related_names  # Same file


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
