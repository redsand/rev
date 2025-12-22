#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Symbol indexing for code-aware retrieval.

This module uses AST parsing to extract and index symbols
(classes, functions, methods, variables) from Python code.
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from rev.debug_logger import get_logger


logger = get_logger()


@dataclass
class Symbol:
    """A code symbol (class, function, variable, etc.)."""
    name: str
    kind: str  # "class", "function", "method", "variable", etc.
    file_path: Path
    line_number: int
    scope: str  # Fully qualified name (e.g., "MyClass.method")
    docstring: Optional[str] = None
    signature: Optional[str] = None  # For functions
    parent: Optional[str] = None  # Parent class/function

    def __hash__(self):
        """Make Symbol hashable for use in sets."""
        return hash((self.name, self.kind, str(self.file_path), self.line_number))

    def __eq__(self, other):
        """Equality comparison for Symbol."""
        if not isinstance(other, Symbol):
            return False
        return (
            self.name == other.name and
            self.kind == other.kind and
            self.file_path == other.file_path and
            self.line_number == other.line_number
        )


class SymbolVisitor(ast.NodeVisitor):
    """AST visitor to extract symbols from Python code."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.symbols: List[Symbol] = []
        self.scope_stack: List[str] = []  # Track current scope

    def _get_scope(self) -> str:
        """Get current fully qualified scope."""
        return ".".join(self.scope_stack) if self.scope_stack else ""

    def _get_docstring(self, node: ast.AST) -> Optional[str]:
        """Extract docstring from a node."""
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and
                node.body and isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)):
            return node.body[0].value.value
        return None

    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        """Extract function signature."""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        return f"{node.name}({', '.join(args)})"

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class definition."""
        scope = self._get_scope()
        full_name = f"{scope}.{node.name}" if scope else node.name

        symbol = Symbol(
            name=node.name,
            kind="class",
            file_path=self.file_path,
            line_number=node.lineno,
            scope=full_name,
            docstring=self._get_docstring(node),
            parent=scope if scope else None
        )
        self.symbols.append(symbol)

        # Enter class scope
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function/method definition."""
        scope = self._get_scope()
        full_name = f"{scope}.{node.name}" if scope else node.name

        # Determine if it's a method or function
        kind = "method" if self.scope_stack else "function"

        symbol = Symbol(
            name=node.name,
            kind=kind,
            file_path=self.file_path,
            line_number=node.lineno,
            scope=full_name,
            docstring=self._get_docstring(node),
            signature=self._get_function_signature(node),
            parent=scope if scope else None
        )
        self.symbols.append(symbol)

        # Enter function scope
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Visit async function definition."""
        # Treat same as regular function
        self.visit_FunctionDef(node)

    def visit_Assign(self, node: ast.Assign):
        """Visit variable assignment."""
        # Only track module-level and class-level variables
        if len(self.scope_stack) <= 1:  # Module or class level
            for target in node.targets:
                if isinstance(target, ast.Name):
                    scope = self._get_scope()
                    full_name = f"{scope}.{target.id}" if scope else target.id

                    symbol = Symbol(
                        name=target.id,
                        kind="variable",
                        file_path=self.file_path,
                        line_number=node.lineno,
                        scope=full_name,
                        parent=scope if scope else None
                    )
                    self.symbols.append(symbol)

        self.generic_visit(node)


class SymbolIndexer:
    """Index symbols using AST parsing."""

    def __init__(self, root: Path):
        """Initialize symbol indexer.

        Args:
            root: Root directory to index
        """
        self.root = root
        self.symbols: Dict[str, List[Symbol]] = {}  # name -> symbols
        self.by_file: Dict[Path, List[Symbol]] = {}  # file -> symbols
        self.by_kind: Dict[str, List[Symbol]] = {}  # kind -> symbols

    def build_index(self, file_patterns: List[str] = None):
        """Parse all matching files and extract symbols.

        Args:
            file_patterns: Glob patterns for files to index (default: ["**/*.py"])
        """
        if file_patterns is None:
            file_patterns = ["**/*.py"]

        logger.log("symbol_index", "BUILD_START", {
            "root": str(self.root),
            "patterns": file_patterns
        }, "INFO")

        file_count = 0
        symbol_count = 0

        for pattern in file_patterns:
            for file_path in self.root.glob(pattern):
                if file_path.is_file():
                    try:
                        symbols = self._parse_file(file_path)
                        self._add_symbols(symbols)
                        file_count += 1
                        symbol_count += len(symbols)
                    except Exception as e:
                        logger.log("symbol_index", "PARSE_ERROR", {
                            "file": str(file_path),
                            "error": str(e)
                        }, "WARNING")

        logger.log("symbol_index", "BUILD_COMPLETE", {
            "files": file_count,
            "symbols": symbol_count
        }, "INFO")

    def _parse_file(self, file_path: Path) -> List[Symbol]:
        """Parse a single file and extract symbols.

        Args:
            file_path: Path to Python file

        Returns:
            List of symbols found in file
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(file_path))
            visitor = SymbolVisitor(file_path)
            visitor.visit(tree)
            return visitor.symbols
        except SyntaxError as e:
            logger.log("symbol_index", "SYNTAX_ERROR", {
                "file": str(file_path),
                "error": str(e)
            }, "WARNING")
            return []

    def _add_symbols(self, symbols: List[Symbol]):
        """Add symbols to index.

        Args:
            symbols: List of symbols to add
        """
        for symbol in symbols:
            # Index by name
            if symbol.name not in self.symbols:
                self.symbols[symbol.name] = []
            self.symbols[symbol.name].append(symbol)

            # Index by file
            if symbol.file_path not in self.by_file:
                self.by_file[symbol.file_path] = []
            self.by_file[symbol.file_path].append(symbol)

            # Index by kind
            if symbol.kind not in self.by_kind:
                self.by_kind[symbol.kind] = []
            self.by_kind[symbol.kind].append(symbol)

    def find_symbol(self, name: str, kind: Optional[str] = None) -> List[Symbol]:
        """Find symbols by name and optionally kind.

        Args:
            name: Symbol name to search for
            kind: Optional kind filter ("class", "function", etc.)

        Returns:
            List of matching symbols
        """
        symbols = self.symbols.get(name, [])

        if kind:
            symbols = [s for s in symbols if s.kind == kind]

        return symbols

    def find_in_file(self, file_path: Path) -> List[Symbol]:
        """Get all symbols in a file.

        Args:
            file_path: Path to file

        Returns:
            List of symbols in file
        """
        return self.by_file.get(file_path, [])

    def find_by_kind(self, kind: str) -> List[Symbol]:
        """Find all symbols of a specific kind.

        Args:
            kind: Symbol kind ("class", "function", "method", "variable")

        Returns:
            List of symbols of that kind
        """
        return self.by_kind.get(kind, [])

    def search_symbols(self, query: str) -> List[Symbol]:
        """Search for symbols matching query.

        Args:
            query: Search query (matches symbol names)

        Returns:
            List of matching symbols
        """
        query_lower = query.lower()
        results = []

        for name, symbols in self.symbols.items():
            if query_lower in name.lower():
                results.extend(symbols)

        return results

    def get_stats(self) -> Dict[str, int]:
        """Get indexing statistics.

        Returns:
            Dictionary with stats (files, symbols, by kind)
        """
        return {
            "files": len(self.by_file),
            "total_symbols": sum(len(symbols) for symbols in self.symbols.values()),
            "classes": len(self.by_kind.get("class", [])),
            "functions": len(self.by_kind.get("function", [])),
            "methods": len(self.by_kind.get("method", [])),
            "variables": len(self.by_kind.get("variable", []))
        }
