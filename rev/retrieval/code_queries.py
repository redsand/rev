#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""High-level code structure queries.

This module provides advanced queries like "find callers", "find implementers",
and "find usages" by combining symbol indexing and AST analysis.
"""

import ast
from pathlib import Path
from typing import List, Tuple, Set

from rev.retrieval.symbol_index import Symbol, SymbolIndexer
from rev.retrieval.import_graph import ImportGraph
from rev.debug_logger import get_logger


logger = get_logger()


class CodeQueryEngine:
    """High-level code structure queries."""

    def __init__(self, symbol_index: SymbolIndexer, import_graph: ImportGraph):
        """Initialize query engine.

        Args:
            symbol_index: Symbol indexer
            import_graph: Import dependency graph
        """
        self.symbols = symbol_index
        self.imports = import_graph

    def find_callers(self, function_name: str) -> List[Tuple[Path, int]]:
        """Find all locations that call a function.

        Args:
            function_name: Name of function to find callers for

        Returns:
            List of (file_path, line_number) tuples where function is called
        """
        logger.log("code_queries", "FIND_CALLERS", {
            "function": function_name
        }, "DEBUG")

        callers = []

        # Search all files for function calls
        for file_path in self.symbols.by_file.keys():
            try:
                call_sites = self._find_calls_in_file(file_path, function_name)
                callers.extend(call_sites)
            except Exception as e:
                logger.log("code_queries", "FIND_CALLERS_ERROR", {
                    "file": str(file_path),
                    "error": str(e)
                }, "WARNING")

        logger.log("code_queries", "FIND_CALLERS_COMPLETE", {
            "function": function_name,
            "callers": len(callers)
        }, "DEBUG")

        return callers

    def _find_calls_in_file(self, file_path: Path, function_name: str) -> List[Tuple[Path, int]]:
        """Find function calls in a specific file.

        Args:
            file_path: Path to file
            function_name: Function name to search for

        Returns:
            List of (file_path, line_number) for calls
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(file_path))
            visitor = CallFinder(file_path, function_name)
            visitor.visit(tree)
            return visitor.calls
        except SyntaxError:
            return []

    def find_implementers(self, base_class: str) -> List[Symbol]:
        """Find all classes that inherit from a base class.

        Args:
            base_class: Name of base class

        Returns:
            List of Symbol objects for subclasses
        """
        logger.log("code_queries", "FIND_IMPLEMENTERS", {
            "base_class": base_class
        }, "DEBUG")

        implementers = []

        # Get all classes
        classes = self.symbols.find_by_kind("class")

        # Check each class for inheritance
        for class_symbol in classes:
            try:
                if self._inherits_from(class_symbol, base_class):
                    implementers.append(class_symbol)
            except Exception as e:
                logger.log("code_queries", "CHECK_INHERITANCE_ERROR", {
                    "class": class_symbol.name,
                    "error": str(e)
                }, "WARNING")

        logger.log("code_queries", "FIND_IMPLEMENTERS_COMPLETE", {
            "base_class": base_class,
            "implementers": len(implementers)
        }, "DEBUG")

        return implementers

    def _inherits_from(self, class_symbol: Symbol, base_class: str) -> bool:
        """Check if a class inherits from a base class.

        Args:
            class_symbol: Symbol for class to check
            base_class: Name of base class

        Returns:
            True if class inherits from base_class
        """
        with open(class_symbol.file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(class_symbol.file_path))
            finder = InheritanceFinder(class_symbol.name, base_class)
            finder.visit(tree)
            return finder.inherits
        except SyntaxError:
            return False

    def find_usages(self, symbol_name: str) -> List[Tuple[Path, int]]:
        """Find all usages of a symbol.

        Args:
            symbol_name: Name of symbol to find usages for

        Returns:
            List of (file_path, line_number) where symbol is used
        """
        logger.log("code_queries", "FIND_USAGES", {
            "symbol": symbol_name
        }, "DEBUG")

        usages = []

        # Search all files for symbol usage
        for file_path in self.symbols.by_file.keys():
            try:
                usage_sites = self._find_usages_in_file(file_path, symbol_name)
                usages.extend(usage_sites)
            except Exception as e:
                logger.log("code_queries", "FIND_USAGES_ERROR", {
                    "file": str(file_path),
                    "error": str(e)
                }, "WARNING")

        logger.log("code_queries", "FIND_USAGES_COMPLETE", {
            "symbol": symbol_name,
            "usages": len(usages)
        }, "DEBUG")

        return usages

    def _find_usages_in_file(self, file_path: Path, symbol_name: str) -> List[Tuple[Path, int]]:
        """Find symbol usages in a specific file.

        Args:
            file_path: Path to file
            symbol_name: Symbol name to search for

        Returns:
            List of (file_path, line_number) for usages
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(file_path))
            visitor = UsageFinder(file_path, symbol_name)
            visitor.visit(tree)
            return visitor.usages
        except SyntaxError:
            return []

    def find_related_symbols(self, symbol: Symbol) -> List[Symbol]:
        """Find symbols related to a given symbol.

        Related symbols include:
        - Symbols in the same file
        - Symbols in files that import this symbol's file
        - Symbols in files imported by this symbol's file

        Args:
            symbol: Symbol to find related symbols for

        Returns:
            List of related symbols
        """
        related = set()

        # Add symbols from same file
        same_file_symbols = self.symbols.find_in_file(symbol.file_path)
        related.update(same_file_symbols)

        # Add symbols from importing files
        module = self.imports._file_to_module(symbol.file_path)
        importers = self.imports.find_importers(module)
        for importer_file in importers:
            importer_symbols = self.symbols.find_in_file(importer_file)
            related.update(importer_symbols)

        # Add symbols from imported files
        dependencies = self.imports.find_dependencies(module)
        for dep_module in dependencies:
            # Find file for this module
            for file_path in self.symbols.by_file.keys():
                if self.imports._file_to_module(file_path) == dep_module:
                    dep_symbols = self.symbols.find_in_file(file_path)
                    related.update(dep_symbols)

        # Remove the original symbol
        related.discard(symbol)

        return list(related)


class CallFinder(ast.NodeVisitor):
    """AST visitor to find function calls."""

    def __init__(self, file_path: Path, function_name: str):
        self.file_path = file_path
        self.function_name = function_name
        self.calls: List[Tuple[Path, int]] = []

    def visit_Call(self, node: ast.Call):
        """Visit function call."""
        # Check if this is a call to our target function
        if isinstance(node.func, ast.Name) and node.func.id == self.function_name:
            self.calls.append((self.file_path, node.lineno))
        elif isinstance(node.func, ast.Attribute) and node.func.attr == self.function_name:
            self.calls.append((self.file_path, node.lineno))

        self.generic_visit(node)


class InheritanceFinder(ast.NodeVisitor):
    """AST visitor to check class inheritance."""

    def __init__(self, class_name: str, base_class: str):
        self.class_name = class_name
        self.base_class = base_class
        self.inherits = False

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definition."""
        if node.name == self.class_name:
            # Check base classes
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == self.base_class:
                    self.inherits = True
                    return
                elif isinstance(base, ast.Attribute) and base.attr == self.base_class:
                    self.inherits = True
                    return

        self.generic_visit(node)


class UsageFinder(ast.NodeVisitor):
    """AST visitor to find symbol usages."""

    def __init__(self, file_path: Path, symbol_name: str):
        self.file_path = file_path
        self.symbol_name = symbol_name
        self.usages: List[Tuple[Path, int]] = []

    def visit_Name(self, node: ast.Name):
        """Visit name reference."""
        if node.id == self.symbol_name:
            self.usages.append((self.file_path, node.lineno))

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        """Visit attribute reference."""
        if node.attr == self.symbol_name:
            self.usages.append((self.file_path, node.lineno))

        self.generic_visit(node)
