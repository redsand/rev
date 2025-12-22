#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import graph analysis for dependency tracking.

This module builds a graph of import dependencies between modules
to enable queries like "what imports this?" and "what does this import?".
"""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from rev.debug_logger import get_logger


logger = get_logger()


@dataclass
class ImportEdge:
    """An import relationship between modules."""
    source_file: Path
    imported_module: str
    imported_names: List[str]  # Specific imports, or ["*"] for wildcard
    import_line: int
    is_relative: bool = False

    def __hash__(self):
        """Make ImportEdge hashable."""
        return hash((str(self.source_file), self.imported_module, self.import_line))


class ImportVisitor(ast.NodeVisitor):
    """AST visitor to extract import statements."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.imports: List[ImportEdge] = []

    def visit_Import(self, node: ast.Import):
        """Visit import statement (e.g., import foo, import bar as baz)."""
        for alias in node.names:
            edge = ImportEdge(
                source_file=self.file_path,
                imported_module=alias.name,
                imported_names=[alias.asname] if alias.asname else [alias.name],
                import_line=node.lineno,
                is_relative=False
            )
            self.imports.append(edge)

        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Visit from...import statement (e.g., from foo import bar)."""
        if node.module:
            # Determine imported names
            imported_names = []
            for alias in node.names:
                if alias.name == "*":
                    imported_names = ["*"]
                    break
                imported_names.append(alias.asname if alias.asname else alias.name)

            edge = ImportEdge(
                source_file=self.file_path,
                imported_module=node.module,
                imported_names=imported_names,
                import_line=node.lineno,
                is_relative=node.level > 0
            )
            self.imports.append(edge)

        self.generic_visit(node)


class ImportGraph:
    """Dependency graph of imports."""

    def __init__(self, root: Path):
        """Initialize import graph.

        Args:
            root: Root directory of codebase
        """
        self.root = root
        self.edges: List[ImportEdge] = []
        self.graph: Dict[str, Set[str]] = {}  # module -> imported modules
        self.reverse_graph: Dict[str, Set[str]] = {}  # module -> modules that import it

    def build_graph(self, file_patterns: List[str] = None):
        """Parse all Python files and build import graph.

        Args:
            file_patterns: Glob patterns for files to parse (default: ["**/*.py"])
        """
        if file_patterns is None:
            file_patterns = ["**/*.py"]

        logger.log("import_graph", "BUILD_START", {
            "root": str(self.root),
            "patterns": file_patterns
        }, "INFO")

        file_count = 0
        import_count = 0

        for pattern in file_patterns:
            for file_path in self.root.glob(pattern):
                if file_path.is_file():
                    try:
                        imports = self._parse_imports(file_path)
                        self._add_imports(imports)
                        file_count += 1
                        import_count += len(imports)
                    except Exception as e:
                        logger.log("import_graph", "PARSE_ERROR", {
                            "file": str(file_path),
                            "error": str(e)
                        }, "WARNING")

        logger.log("import_graph", "BUILD_COMPLETE", {
            "files": file_count,
            "imports": import_count
        }, "INFO")

    def _parse_imports(self, file_path: Path) -> List[ImportEdge]:
        """Parse imports from a single file.

        Args:
            file_path: Path to Python file

        Returns:
            List of import edges
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(file_path))
            visitor = ImportVisitor(file_path)
            visitor.visit(tree)
            return visitor.imports
        except SyntaxError as e:
            logger.log("import_graph", "SYNTAX_ERROR", {
                "file": str(file_path),
                "error": str(e)
            }, "WARNING")
            return []

    def _add_imports(self, imports: List[ImportEdge]):
        """Add imports to graph.

        Args:
            imports: List of import edges
        """
        for edge in imports:
            self.edges.append(edge)

            # Get module name from file path
            source_module = self._file_to_module(edge.source_file)

            # Add to forward graph
            if source_module not in self.graph:
                self.graph[source_module] = set()
            self.graph[source_module].add(edge.imported_module)

            # Add to reverse graph
            if edge.imported_module not in self.reverse_graph:
                self.reverse_graph[edge.imported_module] = set()
            self.reverse_graph[edge.imported_module].add(source_module)

    def _file_to_module(self, file_path: Path) -> str:
        """Convert file path to module name.

        Args:
            file_path: Path to Python file

        Returns:
            Module name (e.g., "rev.tools.registry")
        """
        try:
            # Get relative path from root
            rel_path = file_path.relative_to(self.root)

            # Remove .py extension and convert path separators to dots
            module_path = str(rel_path.with_suffix(''))
            module_name = module_path.replace('\\', '.').replace('/', '.')

            # Remove __init__ suffix
            if module_name.endswith('.__init__'):
                module_name = module_name[:-9]

            return module_name
        except ValueError:
            # File is not relative to root
            return str(file_path.stem)

    def find_importers(self, module: str) -> List[Path]:
        """Find all files that import a module.

        Args:
            module: Module name to search for

        Returns:
            List of file paths that import the module
        """
        importers = self.reverse_graph.get(module, set())
        file_paths = []

        for importer in importers:
            # Find edges for this importer
            for edge in self.edges:
                source_module = self._file_to_module(edge.source_file)
                if source_module == importer and edge.imported_module == module:
                    file_paths.append(edge.source_file)

        return list(set(file_paths))  # Deduplicate

    def find_dependencies(self, module: str) -> Set[str]:
        """Find all modules a module depends on.

        Args:
            module: Module name

        Returns:
            Set of modules this module imports
        """
        return self.graph.get(module, set())

    def find_circular_dependencies(self) -> List[List[str]]:
        """Detect circular import chains.

        Returns:
            List of circular dependency chains
        """
        cycles = []
        visited = set()

        def dfs(node: str, path: List[str]):
            """Depth-first search for cycles."""
            if node in path:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
                return

            if node in visited:
                return

            visited.add(node)
            path.append(node)

            for neighbor in self.graph.get(node, []):
                dfs(neighbor, path[:])

        for module in self.graph.keys():
            dfs(module, [])

        # Deduplicate cycles (same cycle in different order)
        unique_cycles = []
        seen = set()

        for cycle in cycles:
            # Normalize cycle (start from smallest element)
            min_idx = cycle.index(min(cycle))
            normalized = cycle[min_idx:] + cycle[:min_idx]
            cycle_tuple = tuple(normalized)

            if cycle_tuple not in seen:
                seen.add(cycle_tuple)
                unique_cycles.append(cycle)

        return unique_cycles

    def get_import_details(self, source_file: Path, imported_module: str) -> List[ImportEdge]:
        """Get detailed import information.

        Args:
            source_file: Source file path
            imported_module: Module being imported

        Returns:
            List of import edges matching criteria
        """
        return [
            edge for edge in self.edges
            if edge.source_file == source_file and edge.imported_module == imported_module
        ]

    def get_stats(self) -> Dict[str, int]:
        """Get import graph statistics.

        Returns:
            Dictionary with stats
        """
        total_imports = len(self.edges)
        unique_modules = len(self.graph)
        circular_deps = len(self.find_circular_dependencies())

        return {
            "total_imports": total_imports,
            "unique_modules": unique_modules,
            "circular_dependencies": circular_deps
        }
