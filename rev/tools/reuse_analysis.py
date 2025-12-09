#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Code reuse analysis tool (Phase 3).

This module provides tools to analyze code for duplication opportunities
and suggest consolidation strategies.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple
from collections import defaultdict

from rev.config import ROOT
from rev.tools.file_ops import _iter_files, _is_text_file


class ReuseAnalyzer:
    """Analyzes codebase for reuse opportunities and duplication."""

    def __init__(self, root: Path = None):
        """Initialize analyzer.

        Args:
            root: Root directory to analyze (defaults to config.ROOT)
        """
        self.root = root or ROOT

    def find_duplicate_file_names(self, pattern: str = "**/*.py") -> Dict[str, List[str]]:
        """Find files with similar names that might indicate duplication.

        Args:
            pattern: Glob pattern for files to check

        Returns:
            Dict mapping base names to list of file paths
        """
        name_groups = defaultdict(list)

        for file_path in _iter_files(pattern):
            # Group by stem (filename without extension)
            stem = file_path.stem.lower()

            # Normalize common variations
            normalized = re.sub(r'[_-]', '', stem)
            normalized = re.sub(r'(utils?|helpers?|lib)', '', normalized)

            if normalized:
                name_groups[normalized].append(str(file_path.relative_to(self.root)))

        # Filter to only groups with multiple files
        duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}

        return duplicates

    def find_small_utility_files(self, pattern: str = "**/*.py", max_lines: int = 50) -> List[Dict[str, Any]]:
        """Find small utility files that could potentially be consolidated.

        Args:
            pattern: Glob pattern for files to check
            max_lines: Maximum lines to consider a file "small"

        Returns:
            List of small utility files with metadata
        """
        small_files = []

        for file_path in _iter_files(pattern):
            if not _is_text_file(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    line_count = len([l for l in lines if l.strip() and not l.strip().startswith('#')])

                    if line_count <= max_lines and line_count > 0:
                        # Check if it looks like a utility file
                        filename_lower = file_path.name.lower()
                        is_utility = any(word in filename_lower for word in
                                         ['util', 'helper', 'lib', 'common', 'shared', 'tool'])

                        small_files.append({
                            "path": str(file_path.relative_to(self.root)),
                            "lines": line_count,
                            "is_utility": is_utility,
                            "directory": str(file_path.parent.relative_to(self.root))
                        })
            except Exception:
                continue

        return sorted(small_files, key=lambda x: x['lines'])

    def find_duplicate_imports(self, pattern: str = "**/*.py") -> Dict[str, Set[str]]:
        """Find files that import the same external libraries.

        Args:
            pattern: Glob pattern for files to check

        Returns:
            Dict mapping import statements to files that use them
        """
        import_map = defaultdict(set)

        for file_path in _iter_files(pattern):
            if not _is_text_file(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                    # Find import statements
                    imports = re.findall(r'^(?:from|import)\s+(\S+)', content, re.MULTILINE)

                    for imp in imports:
                        # Skip relative imports and standard library (simplified)
                        if not imp.startswith('.') and imp not in {'os', 'sys', 're', 'json', 'pathlib'}:
                            import_map[imp].add(str(file_path.relative_to(self.root)))
            except Exception:
                continue

        # Filter to imports used by multiple files
        return {k: v for k, v in import_map.items() if len(v) > 1}

    def suggest_consolidation(self) -> List[str]:
        """Suggest consolidation opportunities.

        Returns:
            List of consolidation suggestions
        """
        suggestions = []

        # Find duplicate names
        duplicate_names = self.find_duplicate_file_names()
        if duplicate_names:
            suggestions.append(
                f"Found {len(duplicate_names)} groups of files with similar names. "
                "Consider consolidating:"
            )
            for normalized, files in list(duplicate_names.items())[:5]:
                suggestions.append(f"  - {', '.join(files)}")

        # Find small utility files
        small_utils = [f for f in self.find_small_utility_files() if f['is_utility']]
        if small_utils:
            # Group by directory
            by_dir = defaultdict(list)
            for util in small_utils:
                by_dir[util['directory']].append(util)

            dirs_with_multiple = {d: files for d, files in by_dir.items() if len(files) > 1}

            if dirs_with_multiple:
                suggestions.append(
                    f"\nFound {len(small_utils)} small utility files. "
                    f"Consider consolidating in {len(dirs_with_multiple)} directories:"
                )
                for directory, files in list(dirs_with_multiple.items())[:3]:
                    file_list = ', '.join(f['path'] for f in files[:3])
                    suggestions.append(f"  - In {directory}/: {file_list}")

        return suggestions

    def analyze_file_efficiency(self, pattern: str = "**/*.py") -> Dict[str, Any]:
        """Analyze overall file organization efficiency.

        Args:
            pattern: Glob pattern for files to check

        Returns:
            Dict with efficiency metrics
        """
        all_files = list(_iter_files(pattern))
        total_files = len(all_files)

        if total_files == 0:
            return {"error": "No files found"}

        # Count utility files
        utility_count = len([f for f in all_files if any(
            word in f.name.lower() for word in ['util', 'helper', 'lib', 'common', 'shared']
        )])

        # Count small files
        small_file_count = len(self.find_small_utility_files(pattern, max_lines=50))

        # Count duplicate name groups
        duplicate_groups = len(self.find_duplicate_file_names(pattern))

        return {
            "total_files": total_files,
            "utility_files": utility_count,
            "utility_percentage": f"{utility_count / total_files * 100:.1f}%",
            "small_files": small_file_count,
            "small_file_percentage": f"{small_file_count / total_files * 100:.1f}%",
            "duplicate_name_groups": duplicate_groups,
            "consolidation_opportunity": "HIGH" if duplicate_groups > 5 or small_file_count > 10 else "MEDIUM" if duplicate_groups > 2 or small_file_count > 5 else "LOW"
        }


def analyze_reuse_opportunities(pattern: str = "**/*.py") -> str:
    """Analyze codebase for reuse opportunities (tool function).

    Args:
        pattern: Glob pattern for files to analyze

    Returns:
        JSON string with analysis results
    """
    try:
        analyzer = ReuseAnalyzer()

        # Get efficiency metrics
        efficiency = analyzer.analyze_file_efficiency(pattern)

        # Get consolidation suggestions
        suggestions = analyzer.suggest_consolidation()

        result = {
            "efficiency_metrics": efficiency,
            "consolidation_suggestions": suggestions,
            "summary": f"Found {efficiency.get('duplicate_name_groups', 0)} potential duplication issues"
        }

        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Analysis failed: {e}"})


def display_reuse_analysis():
    """Display a formatted reuse analysis report."""
    print("\n" + "=" * 60)
    print("CODE REUSE ANALYSIS REPORT")
    print("=" * 60)

    analyzer = ReuseAnalyzer()

    # Efficiency metrics
    print("\n📊 File Organization Efficiency:")
    efficiency = analyzer.analyze_file_efficiency()
    for key, value in efficiency.items():
        if key != "consolidation_opportunity":
            print(f"  - {key.replace('_', ' ').title()}: {value}")

    print(f"\n  🎯 Consolidation Opportunity: {efficiency['consolidation_opportunity']}")

    # Consolidation suggestions
    print("\n💡 Consolidation Suggestions:")
    suggestions = analyzer.suggest_consolidation()
    if suggestions:
        for suggestion in suggestions:
            print(f"  {suggestion}")
    else:
        print("  ✓ No obvious consolidation opportunities found")

    print("\n" + "=" * 60)
