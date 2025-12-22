#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for import graph analysis."""

import pytest
import tempfile
from pathlib import Path

from rev.retrieval.import_graph import ImportGraph, ImportEdge


class TestImportGraph:
    """Test import graph functionality."""

    def test_parse_simple_imports(self):
        """Verify parsing simple import statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test file
            test_file = tmpdir / "test.py"
            test_file.write_text('''
import os
import sys
from pathlib import Path
''')

            # Build graph
            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Check edges
            assert len(graph.edges) == 3

            # Check modules are tracked
            module = graph._file_to_module(test_file)
            deps = graph.find_dependencies(module)
            assert "os" in deps
            assert "sys" in deps
            assert "pathlib" in deps

    def test_find_importers(self):
        """Verify finding files that import a module."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create module
            module_file = tmpdir / "mymodule.py"
            module_file.write_text('VAR = 1')

            # Create files that import it
            file1 = tmpdir / "file1.py"
            file1.write_text('from mymodule import VAR')

            file2 = tmpdir / "file2.py"
            file2.write_text('import mymodule')

            # Build graph
            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Find importers
            importers = graph.find_importers("mymodule")
            assert len(importers) == 2

    def test_relative_imports(self):
        """Verify tracking relative imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
from . import sibling
from ..parent import something
''')

            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Check relative imports are tracked
            assert any(edge.is_relative for edge in graph.edges)

    def test_wildcard_imports(self):
        """Verify tracking wildcard imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('from mymodule import *')

            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Check wildcard is tracked
            assert any(["*"] == edge.imported_names for edge in graph.edges)

    def test_import_aliases(self):
        """Verify tracking import aliases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
import numpy as np
from pandas import DataFrame as DF
''')

            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Check aliases are tracked
            assert any("np" in edge.imported_names for edge in graph.edges)
            assert any("DF" in edge.imported_names for edge in graph.edges)

    def test_circular_dependencies(self):
        """Verify detecting circular dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create circular dependency
            file_a = tmpdir / "module_a.py"
            file_a.write_text('from module_b import func_b')

            file_b = tmpdir / "module_b.py"
            file_b.write_text('from module_a import func_a')

            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Detect cycles
            cycles = graph.find_circular_dependencies()
            assert len(cycles) > 0

    def test_get_import_details(self):
        """Verify getting detailed import information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
from mymodule import func1, func2
from mymodule import func3
''')

            graph = ImportGraph(tmpdir)
            graph.build_graph()

            # Get details for specific import
            details = graph.get_import_details(test_file, "mymodule")
            assert len(details) == 2  # Two import statements

    def test_get_stats(self):
        """Verify statistics collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            test_file = tmpdir / "test.py"
            test_file.write_text('''
import os
import sys
from pathlib import Path
''')

            graph = ImportGraph(tmpdir)
            graph.build_graph()

            stats = graph.get_stats()
            assert stats["total_imports"] == 3
            assert stats["unique_modules"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
