#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Advanced code analysis tools for improved development, review, and bug fixes.

This module provides comprehensive analysis capabilities:
- Test coverage analysis
- Code context and history
- Symbol usage tracking
- Dependency graph analysis
- Semantic diff detection
"""

import json
import ast
import re
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple, Optional
from collections import defaultdict

from rev import config
from rev.tools.utils import _run_shell, _safe_path, quote_cmd_arg
from rev.cache import get_ast_cache


def analyze_test_coverage(path: str = ".", show_untested: bool = True) -> str:
    """Analyze test coverage for code paths.

    Integrates with coverage.py (Python), Istanbul/nyc (JavaScript/TypeScript).
    Identifies untested code to guide development and prevent bugs.

    Args:
        path: Path to analyze coverage for
        show_untested: If True, highlight untested functions/lines

    Returns:
        JSON string with coverage analysis
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        results = {
            "coverage_data": {},
            "uncovered_files": [],
            "critical_gaps": [],
            "recommendations": []
        }

        # Try Python coverage first
        python_coverage = _analyze_python_coverage(scan_path)
        if python_coverage:
            results["coverage_data"]["python"] = python_coverage

        # Try JavaScript/TypeScript coverage
        js_coverage = _analyze_js_coverage(scan_path)
        if js_coverage:
            results["coverage_data"]["javascript"] = js_coverage

        # If no coverage tools found, scan for test files and infer coverage
        if not results["coverage_data"]:
            inferred = _infer_test_coverage(scan_path)
            results["coverage_data"]["inferred"] = inferred

        # Identify critical gaps
        for lang, coverage in results["coverage_data"].items():
            if "uncovered_functions" in coverage:
                for func in coverage["uncovered_functions"]:
                    if any(keyword in func.lower() for keyword in ["auth", "payment", "security", "validate"]):
                        results["critical_gaps"].append({
                            "function": func,
                            "reason": "Critical security/business logic without tests",
                            "language": lang
                        })

        # Generate recommendations
        if results["critical_gaps"]:
            results["recommendations"].append(
                f"Add tests for {len(results['critical_gaps'])} critical functions before modifying"
            )

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Coverage analysis failed: {type(e).__name__}: {e}"})


def _analyze_python_coverage(path: Path) -> Optional[Dict[str, Any]]:
    """Analyze Python test coverage using coverage.py."""
    try:
        # Check if .coverage file exists
        coverage_file = path / ".coverage" if path.is_dir() else path.parent / ".coverage"
        if not coverage_file.exists():
            return None

        # Run coverage report (cross-platform temp file)
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
            tmp_path = tmp_file.name

        try:
            cmd = f"coverage json -o {quote_cmd_arg(tmp_path)}"
            proc = _run_shell(cmd, timeout=30)

            if proc.returncode != 0:
                return None

            # Parse coverage JSON
            with open(tmp_path, "r") as f:
                coverage_data = json.load(f)
        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except:
                pass

        total_statements = coverage_data.get("totals", {}).get("num_statements", 0)
        covered_statements = coverage_data.get("totals", {}).get("covered_lines", 0)
        coverage_pct = coverage_data.get("totals", {}).get("percent_covered", 0)

        uncovered_files = []
        for file_path, file_data in coverage_data.get("files", {}).items():
            if file_data.get("summary", {}).get("percent_covered", 100) < 80:
                uncovered_files.append({
                    "file": file_path,
                    "coverage": file_data["summary"]["percent_covered"],
                    "missing_lines": file_data.get("missing_lines", [])
                })

        return {
            "total_statements": total_statements,
            "covered_statements": covered_statements,
            "coverage_percentage": coverage_pct,
            "uncovered_files": uncovered_files[:10]
        }

    except Exception:
        return None


def _analyze_js_coverage(path: Path) -> Optional[Dict[str, Any]]:
    """Analyze JavaScript/TypeScript coverage using Istanbul/nyc."""
    try:
        # Check if coverage directory exists
        coverage_dir = path / "coverage" if path.is_dir() else path.parent / "coverage"
        coverage_json = coverage_dir / "coverage-summary.json"

        if not coverage_json.exists():
            return None

        with open(coverage_json, "r") as f:
            coverage_data = json.load(f)

        total = coverage_data.get("total", {})

        return {
            "lines": total.get("lines", {}).get("pct", 0),
            "statements": total.get("statements", {}).get("pct", 0),
            "functions": total.get("functions", {}).get("pct", 0),
            "branches": total.get("branches", {}).get("pct", 0)
        }

    except Exception:
        return None


def _infer_test_coverage(path: Path) -> Dict[str, Any]:
    """Infer test coverage by comparing source files to test files."""
    try:
        source_files = set()
        test_files = set()

        if path.is_dir():
            # Find source files
            for ext in [".py", ".js", ".ts", ".jsx", ".tsx"]:
                source_files.update(
                    str(f.relative_to(path)) for f in path.rglob(f"*{ext}")
                    if "test" not in str(f) and "spec" not in str(f)
                )

            # Find test files
            for pattern in ["test_*.py", "*_test.py", "*.test.js", "*.test.ts", "*.spec.js", "*.spec.ts"]:
                test_files.update(str(f.relative_to(path)) for f in path.rglob(pattern))

        # Infer which source files have tests
        covered = 0
        for src in source_files:
            src_name = Path(src).stem
            if any(src_name in test for test in test_files):
                covered += 1

        coverage_pct = (covered / len(source_files) * 100) if source_files else 0

        return {
            "total_source_files": len(source_files),
            "files_with_tests": covered,
            "estimated_coverage": round(coverage_pct, 1),
            "note": "Inferred from file naming patterns (test_*, *.test.*, *.spec.*)"
        }

    except Exception as e:
        return {"error": str(e)}


def analyze_code_context(file_path: str, line_range: Optional[Tuple[int, int]] = None) -> str:
    """Provide historical context for code using git history and analysis.

    Helps understand WHY code exists, what bugs were fixed, and change patterns.

    Args:
        file_path: Path to file to analyze
        line_range: Optional (start_line, end_line) tuple to focus analysis

    Returns:
        JSON string with code context and history
    """
    try:
        file = _safe_path(file_path)
        if not file.exists():
            return json.dumps({"error": f"File not found: {file_path}"})

        rel_path = file.relative_to(config.ROOT).as_posix()

        results = {
            "file": rel_path,
            "line_range": line_range,
            "git_history": {},
            "change_metrics": {},
            "comments": [],
            "warnings": []
        }

        # Get git blame for context
        blame_cmd = f"git blame -p {rel_path}"
        if line_range:
            blame_cmd += f" -L {line_range[0]},{line_range[1]}"

        blame_proc = _run_shell(blame_cmd, timeout=30)
        if blame_proc.returncode == 0:
            results["git_history"] = _parse_git_blame(blame_proc.stdout)

        # Get commit history for file
        log_cmd = f"git log --follow --format='%H|%an|%ae|%ad|%s' -n 20 -- {rel_path}"
        log_proc = _run_shell(log_cmd, timeout=30)
        if log_proc.returncode == 0:
            commits = []
            for line in log_proc.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    if len(parts) == 5:
                        commits.append({
                            "hash": parts[0][:8],
                            "author": parts[1],
                            "email": parts[2],
                            "date": parts[3],
                            "message": parts[4]
                        })
            results["git_history"]["commits"] = commits

            # Analyze commit messages for bug fixes
            bug_fixes = [c for c in commits if any(keyword in c["message"].lower()
                                                   for keyword in ["fix", "bug", "issue", "error"])]
            results["git_history"]["bug_fix_count"] = len(bug_fixes)
            results["git_history"]["recent_bug_fixes"] = bug_fixes[:5]

        # Calculate churn metrics
        churn_cmd = f"git log --format= --numstat -- {rel_path}"
        churn_proc = _run_shell(churn_cmd, timeout=30)
        if churn_proc.returncode == 0:
            changes = churn_proc.stdout.strip().split('\n')
            total_changes = len([c for c in changes if c])

            # Calculate stability score (inverse of churn)
            if total_changes > 10:
                stability = "low"
                results["warnings"].append(
                    f"High churn detected ({total_changes} changes) - proceed with caution"
                )
            elif total_changes > 5:
                stability = "medium"
            else:
                stability = "high"

            results["change_metrics"] = {
                "total_changes": total_changes,
                "stability": stability,
                "change_frequency": "high" if total_changes > 10 else "medium" if total_changes > 5 else "low"
            }

        # Extract code comments
        try:
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Find TODO, FIXME, IMPORTANT, WARNING comments
            comment_patterns = [
                (r'#\s*(TODO|FIXME|IMPORTANT|WARNING|NOTE):?\s*(.+)', 'python'),
                (r'//\s*(TODO|FIXME|IMPORTANT|WARNING|NOTE):?\s*(.+)', 'js/ts'),
                (r'/\*\s*(TODO|FIXME|IMPORTANT|WARNING|NOTE):?\s*(.+?)\*/', 'js/ts')
            ]

            for pattern, lang in comment_patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    results["comments"].append({
                        "type": match.group(1).upper(),
                        "text": match.group(2).strip(),
                        "language": lang
                    })
        except Exception:
            pass

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Context analysis failed: {type(e).__name__}: {e}"})


def _parse_git_blame(blame_output: str) -> Dict[str, Any]:
    """Parse git blame output for context."""
    try:
        lines = blame_output.split('\n')
        authors = set()
        commits = set()

        for line in lines:
            if line.startswith('author '):
                authors.add(line[7:])
            elif line.startswith('summary '):
                commits.add(line[8:])

        return {
            "unique_authors": len(authors),
            "unique_commits": len(commits),
            "authors": list(authors)[:5]
        }
    except Exception:
        return {}


def find_symbol_usages(symbol: str, scope: str = "project") -> str:
    """Find all usages of a symbol (function, class, variable) across codebase.

    Critical for understanding impact before renaming, deleting, or modifying.

    Args:
        symbol: Symbol name to find (e.g., "UserRole", "authenticate")
        scope: Search scope ("project", "file", "directory")

    Returns:
        JSON string with all symbol usages
    """
    try:
        results = {
            "symbol": symbol,
            "total_usages": 0,
            "usages": [],
            "files_affected": [],
            "safe_to_delete": False,
            "safe_to_rename": False,
            "rename_impact": "UNKNOWN"
        }

        # Search for symbol in Python files
        python_usages = _find_python_symbol_usages(symbol)
        results["usages"].extend(python_usages)

        # Search for symbol in TypeScript/JavaScript files
        ts_usages = _find_typescript_symbol_usages(symbol)
        results["usages"].extend(ts_usages)

        # Search for symbol in other files (grep fallback)
        other_usages = _find_symbol_with_grep(symbol)
        results["usages"].extend(other_usages)

        results["total_usages"] = len(results["usages"])
        results["files_affected"] = list(set(u["file"] for u in results["usages"]))

        # Determine safety
        if results["total_usages"] == 0:
            results["safe_to_delete"] = True
            results["rename_impact"] = "NONE"
        elif results["total_usages"] <= 3:
            results["safe_to_rename"] = True
            results["rename_impact"] = "LOW"
        elif results["total_usages"] <= 10:
            results["safe_to_rename"] = True
            results["rename_impact"] = "MEDIUM"
        else:
            results["safe_to_rename"] = False
            results["rename_impact"] = "HIGH"

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Symbol usage analysis failed: {type(e).__name__}: {e}"})


def _find_python_symbol_usages(symbol: str) -> List[Dict[str, Any]]:
    """Find Python symbol usages using AST parsing."""
    usages = []

    try:
        for py_file in config.ROOT.rglob("*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    # Check function/class definitions
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        if node.name == symbol:
                            usages.append({
                                "file": py_file.relative_to(config.ROOT).as_posix(),
                                "line": node.lineno,
                                "type": "definition",
                                "context": f"{'def' if isinstance(node, ast.FunctionDef) else 'class'} {symbol}"
                            })

                    # Check name references
                    elif isinstance(node, ast.Name) and node.id == symbol:
                        usages.append({
                            "file": py_file.relative_to(config.ROOT).as_posix(),
                            "line": node.lineno,
                            "type": "reference",
                            "context": f"Usage of {symbol}"
                        })
                    
                    # Check imports (added)
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == symbol or alias.name.split('.')[0] == symbol:
                                usages.append({
                                    "file": py_file.relative_to(config.ROOT).as_posix(),
                                    "line": node.lineno,
                                    "type": "import",
                                    "context": f"import {alias.name}"
                                })
                    
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and (node.module == symbol or node.module.startswith(symbol + '.')):
                            usages.append({
                                "file": py_file.relative_to(config.ROOT).as_posix(),
                                "line": node.lineno,
                                "type": "import",
                                "context": f"from {node.module} import ..."
                            })
                        for alias in node.names:
                            if alias.name == symbol:
                                usages.append({
                                    "file": py_file.relative_to(config.ROOT).as_posix(),
                                    "line": node.lineno,
                                    "type": "import",
                                    "context": f"from {node.module or ''} import {alias.name}"
                                })
            except Exception:
                continue

    except Exception:
        pass

    return usages


def _find_typescript_symbol_usages(symbol: str) -> List[Dict[str, Any]]:
    """Find TypeScript/JavaScript symbol usages using regex patterns."""
    usages = []

    try:
        patterns = [
            rf'\bclass\s+{symbol}\b',
            rf'\binterface\s+{symbol}\b',
            rf'\btype\s+{symbol}\b',
            rf'\benum\s+{symbol}\b',
            rf'\bfunction\s+{symbol}\b',
            rf'\bconst\s+{symbol}\b',
            rf'\b{symbol}\(',  # Function call
            rf'\b{symbol}\.',  # Property access
        ]

        for ext in [".ts", ".tsx", ".js", ".jsx"]:
            for file in config.ROOT.rglob(f"*{ext}"):
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        content = f.read()

                    for line_num, line in enumerate(content.split('\n'), 1):
                        for pattern in patterns:
                            if re.search(pattern, line):
                                usages.append({
                                    "file": file.relative_to(config.ROOT).as_posix(),
                                    "line": line_num,
                                    "type": "usage",
                                    "context": line.strip()[:100]
                                })
                                break  # Don't count same line multiple times
                except Exception:
                    continue
    except Exception:
        pass

    return usages


def _find_symbol_with_grep(symbol: str) -> List[Dict[str, Any]]:
    """Fallback: find symbol using grep.

    SECURITY: symbol is properly quoted to prevent command injection.
    """
    usages = []

    try:
        # Use quote_cmd_arg to prevent command injection
        quoted_symbol = quote_cmd_arg(symbol)
        cmd = f"grep -rn '\\b{quoted_symbol}\\b' . --include='*.py' --include='*.ts' --include='*.js' --include='*.tsx' --include='*.jsx' 2>/dev/null | head -50"
        proc = _run_shell(cmd, timeout=30)

        if proc.returncode == 0:
            for line in proc.stdout.split('\n'):
                if ':' in line:
                    parts = line.split(':', 2)
                    if len(parts) == 3:
                        usages.append({
                            "file": parts[0].lstrip('./'),
                            "line": parts[1],
                            "type": "grep_match",
                            "context": parts[2].strip()[:100]
                        })
    except Exception:
        pass

    return usages


def analyze_dependencies(target: str, depth: int = 3) -> str:
    """Build dependency graph and impact analysis.

    Shows what code depends on the target and what the target depends on.
    Critical for understanding ripple effects of changes.

    Args:
        target: File path or symbol to analyze
        depth: Dependency traversal depth

    Returns:
        JSON string with dependency graph and impact analysis
    """
    try:
        results = {
            "target": target,
            "used_by": [],
            "depends_on": [],
            "impact_radius": {
                "direct": 0,
                "transitive": 0,
                "risk_level": "UNKNOWN"
            },
            "circular_dependencies": []
        }

        # Determine if target is a file or symbol
        target_path = _safe_path(target)
        if target_path.exists():
            # File-based dependency analysis
            deps = _analyze_file_dependencies(target_path, depth)
            results.update(deps)
        else:
            # Symbol-based dependency analysis
            deps = _analyze_symbol_dependencies(target, depth)
            results.update(deps)

        # Calculate impact
        results["impact_radius"]["direct"] = len(results["used_by"])
        results["impact_radius"]["transitive"] = len(results["depends_on"])

        total_impact = results["impact_radius"]["direct"] + results["impact_radius"]["transitive"]
        if total_impact > 20:
            results["impact_radius"]["risk_level"] = "HIGH"
        elif total_impact > 10:
            results["impact_radius"]["risk_level"] = "MEDIUM"
        else:
            results["impact_radius"]["risk_level"] = "LOW"

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Dependency analysis failed: {type(e).__name__}: {e}"})


def _analyze_file_dependencies(file_path: Path, depth: int) -> Dict[str, Any]:
    """Analyze dependencies for a specific file."""
    try:
        deps = {
            "used_by": [],
            "depends_on": [],
            "circular_dependencies": []
        }

        rel_path = file_path.relative_to(config.ROOT).as_posix()

        # Find what this file imports/requires
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Python imports
        if file_path.suffix == '.py':
            for match in re.finditer(r'^\s*(?:from|import)\s+([a-zA-Z0-9_.]+)', content, re.MULTILINE):
                deps["depends_on"].append(match.group(1))

        # TypeScript/JavaScript imports
        elif file_path.suffix in ['.ts', '.tsx', '.js', '.jsx']:
            for match in re.finditer(r'import\s+.+\s+from\s+[\'"](.+?)[\'"]', content):
                deps["depends_on"].append(match.group(1))

        # Find what imports this file (reverse dependencies)
        # Use our improved find_symbol_usages for accurate detection
        module_path = rel_path.replace('.py', '').replace('/', '.')
        
        usages_json = find_symbol_usages(module_path)
        usages = json.loads(usages_json)
        
        for usage in usages.get("usages", []):
            if usage["file"] != rel_path and usage["file"] not in deps["used_by"]:
                deps["used_by"].append(usage["file"])

        return deps

    except Exception:
        return {"used_by": [], "depends_on": [], "circular_dependencies": []}


def _analyze_symbol_dependencies(symbol: str, depth: int) -> Dict[str, Any]:
    """Analyze dependencies for a symbol."""
    # Simplified version - find where symbol is used
    usages_result = find_symbol_usages(symbol)
    usages = json.loads(usages_result)

    return {
        "used_by": [u["file"] for u in usages.get("usages", [])],
        "depends_on": [],
        "circular_dependencies": []
    }


def analyze_semantic_diff(file_path: str, compare_to: str = "HEAD") -> str:
    """Analyze semantic changes beyond line diffs.

    Detects breaking changes, behavior changes, and performance impacts.

    Args:
        file_path: Path to file to analyze
        compare_to: Git ref to compare against (default: HEAD)

    Returns:
        JSON string with semantic diff analysis
    """
    try:
        file = _safe_path(file_path)
        if not file.exists():
            return json.dumps({"error": f"File not found: {file_path}"})

        rel_path = file.relative_to(config.ROOT).as_posix()

        results = {
            "file": rel_path,
            "compared_to": compare_to,
            "changes": [],
            "backward_compatible": True,
            "migration_required": False,
            "summary": {}
        }

        # Get old version from git
        old_cmd = f"git show {compare_to}:{rel_path}"
        old_proc = _run_shell(old_cmd, timeout=30)

        if old_proc.returncode != 0:
            return json.dumps({"error": "Could not retrieve old version from git"})

        old_content = old_proc.stdout

        # Get current version
        with open(file, 'r', encoding='utf-8') as f:
            new_content = f.read()

        # Analyze based on file type
        if file.suffix == '.py':
            changes = _analyze_python_semantic_diff(old_content, new_content)
        elif file.suffix in ['.ts', '.js', '.tsx', '.jsx']:
            changes = _analyze_js_semantic_diff(old_content, new_content)
        else:
            changes = []

        results["changes"] = changes

        # Determine compatibility
        breaking_changes = [c for c in changes if c.get("type") == "BREAKING_CHANGE"]
        if breaking_changes:
            results["backward_compatible"] = False
            results["migration_required"] = True

        results["summary"] = {
            "total_changes": len(changes),
            "breaking_changes": len(breaking_changes),
            "behavior_changes": len([c for c in changes if c.get("type") == "BEHAVIOR_CHANGE"]),
            "performance_changes": len([c for c in changes if c.get("type") == "PERFORMANCE_CHANGE"])
        }

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Semantic diff failed: {type(e).__name__}: {e}"})


def _analyze_python_semantic_diff(old_content: str, new_content: str) -> List[Dict[str, Any]]:
    """Analyze semantic changes in Python code."""
    changes = []

    try:
        old_tree = ast.parse(old_content)
        new_tree = ast.parse(new_content)

        # Extract function signatures
        old_functions = {}
        new_functions = {}

        # Python 3.9+ has ast.unparse, 3.8 needs fallback
        import sys
        has_unparse = sys.version_info >= (3, 9)

        for node in ast.walk(old_tree):
            if isinstance(node, ast.FunctionDef):
                if has_unparse:
                    return_type = ast.unparse(node.returns) if node.returns else None
                else:
                    # Fallback for Python 3.8: use ast.get_source_segment
                    return_type = ast.get_source_segment(old_content, node.returns) if node.returns else None
                old_functions[node.name] = {
                    "args": [arg.arg for arg in node.args.args],
                    "returns": return_type
                }

        for node in ast.walk(new_tree):
            if isinstance(node, ast.FunctionDef):
                if has_unparse:
                    return_type = ast.unparse(node.returns) if node.returns else None
                else:
                    # Fallback for Python 3.8
                    return_type = ast.get_source_segment(new_content, node.returns) if node.returns else None
                new_functions[node.name] = {
                    "args": [arg.arg for arg in node.args.args],
                    "returns": return_type
                }

        # Compare signatures
        for func_name in set(old_functions.keys()) & set(new_functions.keys()):
            old_func = old_functions[func_name]
            new_func = new_functions[func_name]

            # Check argument changes
            if old_func["args"] != new_func["args"]:
                changes.append({
                    "type": "BREAKING_CHANGE",
                    "severity": "HIGH",
                    "description": f"Function '{func_name}' signature changed",
                    "old": f"{func_name}({', '.join(old_func['args'])})",
                    "new": f"{func_name}({', '.join(new_func['args'])})",
                    "impact": "All callers must be updated"
                })

            # Check return type changes
            if old_func["returns"] != new_func["returns"]:
                changes.append({
                    "type": "BREAKING_CHANGE",
                    "severity": "MEDIUM",
                    "description": f"Function '{func_name}' return type changed",
                    "old": old_func["returns"] or "None",
                    "new": new_func["returns"] or "None",
                    "impact": "Callers may need type adjustments"
                })

        # Check for deleted functions
        deleted = set(old_functions.keys()) - set(new_functions.keys())
        for func_name in deleted:
            changes.append({
                "type": "BREAKING_CHANGE",
                "severity": "CRITICAL",
                "description": f"Function '{func_name}' deleted",
                "impact": "All callers will break"
            })

    except Exception:
        pass

    return changes


def _analyze_js_semantic_diff(old_content: str, new_content: str) -> List[Dict[str, Any]]:
    """Analyze semantic changes in JavaScript/TypeScript code."""
    changes = []

    # Simplified regex-based analysis for JS/TS
    # Look for function signature changes
    old_functions = set(re.findall(r'function\s+(\w+)\s*\([^)]*\)', old_content))
    new_functions = set(re.findall(r'function\s+(\w+)\s*\([^)]*\)', new_content))

    deleted = old_functions - new_functions
    for func in deleted:
        changes.append({
            "type": "BREAKING_CHANGE",
            "severity": "CRITICAL",
            "description": f"Function '{func}' deleted or renamed"
        })

    return changes
