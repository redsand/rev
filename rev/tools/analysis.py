#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static code analysis and AST-based tools for comprehensive code quality checks.

This module provides cross-platform (Windows/Linux/macOS) static analysis tools:
- AST-based pattern matching and code analysis (with intelligent caching)
- pylint: comprehensive static code analysis
- mypy: static type checking
- radon: code complexity metrics (cyclomatic, maintainability)
- vulture: dead code detection
- bandit: security vulnerability scanning (via security.py)

Performance: AST analysis caching provides 10-1000x speedup on cache hits.
"""

import ast
import json
import shlex
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from rev.config import ROOT
from rev.tools.utils import _run_shell, _safe_path
from rev.cache import get_ast_cache


@dataclass
class ASTPattern:
    """Pattern for AST-based code matching."""
    name: str
    description: str
    node_type: type
    check_func: callable


def analyze_ast_patterns(path: str, patterns: Optional[List[str]] = None) -> str:
    """Analyze Python code using AST for pattern matching.

    More accurate than regex for code analysis. Detects:
    - TODO/FIXME comments
    - Print statements (potential debug code)
    - Dangerous functions (eval, exec, compile)
    - Missing type hints
    - Complex functions (many parameters)
    - Global variable usage

    Performance: Uses intelligent caching (10-1000x speedup on cache hits).
    Files are cached by path + mtime + patterns to ensure correctness.

    Args:
        path: Path to Python file or directory
        patterns: Specific patterns to check (default: all)

    Returns:
        JSON string with AST analysis results
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        # Collect Python files
        if scan_path.is_file():
            python_files = [scan_path] if scan_path.suffix == '.py' else []
        else:
            python_files = list(scan_path.rglob('*.py'))

        if not python_files:
            return json.dumps({"error": "No Python files found"})

        results: Dict[str, Any] = {
            "scanned_files": len(python_files),
            "files": {}
        }

        all_patterns = patterns or [
            "todos", "prints", "dangerous", "type_hints",
            "complex_functions", "globals"
        ]

        # Get AST cache instance
        ast_cache = get_ast_cache()
        cache_hits = 0
        cache_misses = 0

        for py_file in python_files:
            # CHECK CACHE FIRST for massive speedup
            if ast_cache is not None:
                cached_result = ast_cache.get_file_analysis(py_file, all_patterns)
                if cached_result is not None:
                    # Cache hit! Skip expensive AST parsing
                    rel_path = str(py_file.relative_to(ROOT))
                    results["files"][rel_path] = cached_result
                    cache_hits += 1
                    continue

            # Cache miss - need to parse and analyze
            cache_misses += 1

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    source = f.read()

                tree = ast.parse(source, filename=str(py_file))
                file_issues: Dict[str, List[Dict[str, Any]]] = {}

                # Pattern: TODO/FIXME comments
                if "todos" in all_patterns:
                    todos = []
                    for lineno, line in enumerate(source.splitlines(), 1):
                        if 'TODO' in line or 'FIXME' in line:
                            todos.append({
                                "line": lineno,
                                "text": line.strip(),
                                "type": "TODO" if "TODO" in line else "FIXME"
                            })
                    if todos:
                        file_issues["todos"] = todos

                # Pattern: Print statements (potential debug code)
                if "prints" in all_patterns:
                    prints = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name) and node.func.id == 'print':
                                prints.append({
                                    "line": node.lineno,
                                    "type": "print_statement"
                                })
                    if prints:
                        file_issues["print_statements"] = prints

                # Pattern: Dangerous functions
                if "dangerous" in all_patterns:
                    dangerous = []
                    dangerous_funcs = {'eval', 'exec', 'compile', '__import__'}
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name) and node.func.id in dangerous_funcs:
                                dangerous.append({
                                    "line": node.lineno,
                                    "function": node.func.id,
                                    "severity": "HIGH"
                                })
                    if dangerous:
                        file_issues["dangerous_functions"] = dangerous

                # Pattern: Missing type hints
                if "type_hints" in all_patterns:
                    missing_hints = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            if not node.returns and not node.name.startswith('_'):
                                missing_hints.append({
                                    "line": node.lineno,
                                    "function": node.name,
                                    "issue": "missing_return_type"
                                })
                    if missing_hints:
                        file_issues["missing_type_hints"] = missing_hints

                # Pattern: Complex functions (many parameters)
                if "complex_functions" in all_patterns:
                    complex_funcs = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            param_count = len(node.args.args)
                            if param_count > 5:
                                complex_funcs.append({
                                    "line": node.lineno,
                                    "function": node.name,
                                    "parameters": param_count,
                                    "suggestion": "Consider using dataclass or config object"
                                })
                    if complex_funcs:
                        file_issues["complex_functions"] = complex_funcs

                # Pattern: Global variables
                if "globals" in all_patterns:
                    globals_found = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Global):
                            globals_found.append({
                                "line": node.lineno,
                                "variables": node.names
                            })
                    if globals_found:
                        file_issues["global_variables"] = globals_found

                if file_issues:
                    rel_path = str(py_file.relative_to(ROOT))
                    results["files"][rel_path] = file_issues

                    # CACHE THE RESULT for future calls
                    if ast_cache is not None:
                        ast_cache.set_file_analysis(py_file, all_patterns, file_issues)

            except Exception as e:
                rel_path = str(py_file.relative_to(ROOT))
                results["files"][rel_path] = {
                    "error": f"Failed to parse: {type(e).__name__}"
                }

        # Summary
        total_issues = sum(
            len(issues)
            for file_issues in results["files"].values()
            for issues in file_issues.values() if isinstance(issues, list)
        )

        results["total_issues"] = total_issues
        results["patterns_checked"] = all_patterns

        # Add cache statistics
        if cache_hits > 0 or cache_misses > 0:
            total_files = cache_hits + cache_misses
            hit_rate = (cache_hits / total_files * 100) if total_files > 0 else 0
            results["cache_stats"] = {
                "hits": cache_hits,
                "misses": cache_misses,
                "hit_rate_percent": round(hit_rate, 1)
            }

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"AST analysis failed: {type(e).__name__}: {e}"})


def run_pylint(path: str = ".", config: Optional[str] = None) -> str:
    """Run pylint static code analysis.

    Pylint checks for:
    - Code errors and bugs
    - Code style violations (PEP 8)
    - Code smells and anti-patterns
    - Unused imports and variables
    - Naming conventions

    Args:
        path: Path to analyze
        config: Path to pylintrc config file (optional)

    Returns:
        JSON string with pylint results
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        cmd_parts = ["pylint", "--output-format=json"]

        if config:
            config_path = _safe_path(config)
            if config_path.exists():
                cmd_parts.append(f"--rcfile={shlex.quote(str(config_path))}")

        cmd_parts.append(shlex.quote(str(scan_path)))
        cmd = " ".join(cmd_parts)

        proc = _run_shell(cmd, timeout=180)

        if proc.returncode == 127:
            return json.dumps({
                "error": "pylint not installed",
                "install": "pip install pylint"
            })

        try:
            issues = json.loads(proc.stdout) if proc.stdout else []

            # Categorize by severity
            by_type: Dict[str, List[Dict[str, Any]]] = {
                "convention": [],
                "refactor": [],
                "warning": [],
                "error": [],
                "fatal": []
            }

            for issue in issues:
                issue_type = issue.get("type", "").lower()
                if issue_type in by_type:
                    by_type[issue_type].append(issue)

            # Calculate score (pylint outputs it in stderr)
            score = None
            if proc.stderr:
                for line in proc.stderr.splitlines():
                    if "rated at" in line.lower():
                        try:
                            score = float(line.split("rated at")[1].split("/")[0].strip())
                        except Exception:
                            pass

            return json.dumps({
                "tool": "pylint",
                "scanned": str(scan_path.relative_to(ROOT)),
                "total_issues": len(issues),
                "by_type": {k: len(v) for k, v in by_type.items()},
                "issues": issues,
                "score": score,
                "details_by_type": by_type
            }, indent=2)

        except json.JSONDecodeError:
            return json.dumps({
                "tool": "pylint",
                "scanned": str(scan_path.relative_to(ROOT)),
                "message": "Analysis completed",
                "output": proc.stdout[:500] if proc.stdout else ""
            })

    except Exception as e:
        return json.dumps({"error": f"Pylint analysis failed: {type(e).__name__}: {e}"})


def run_mypy(path: str = ".", config: Optional[str] = None) -> str:
    """Run mypy static type checking.

    Mypy verifies type hints and catches type-related bugs before runtime.

    Args:
        path: Path to analyze
        config: Path to mypy.ini config file (optional)

    Returns:
        JSON string with mypy results
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        cmd_parts = ["mypy", "--show-error-codes", "--no-error-summary"]

        if config:
            config_path = _safe_path(config)
            if config_path.exists():
                cmd_parts.append(f"--config-file={shlex.quote(str(config_path))}")

        cmd_parts.append(shlex.quote(str(scan_path)))
        cmd = " ".join(cmd_parts)

        proc = _run_shell(cmd, timeout=180)

        if proc.returncode == 127:
            return json.dumps({
                "error": "mypy not installed",
                "install": "pip install mypy"
            })

        # Parse mypy output
        issues = []
        if proc.stdout:
            for line in proc.stdout.splitlines():
                if ": error:" in line or ": warning:" in line or ": note:" in line:
                    parts = line.split(":", 3)
                    if len(parts) >= 4:
                        issues.append({
                            "file": parts[0].strip(),
                            "line": parts[1].strip(),
                            "severity": parts[2].strip(),
                            "message": parts[3].strip()
                        })

        by_severity = {}
        for issue in issues:
            sev = issue.get("severity", "error")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return json.dumps({
            "tool": "mypy",
            "scanned": str(scan_path.relative_to(ROOT)),
            "total_issues": len(issues),
            "by_severity": by_severity,
            "issues": issues,
            "success": proc.returncode == 0
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Mypy analysis failed: {type(e).__name__}: {e}"})


def run_radon_complexity(path: str = ".", min_rank: str = "C") -> str:
    """Analyze code complexity using radon.

    Measures:
    - Cyclomatic complexity (how many paths through code)
    - Maintainability index (A=high, F=low)
    - Raw metrics (LOC, LLOC, comments)

    Args:
        path: Path to analyze
        min_rank: Minimum complexity rank to report (A-F)

    Returns:
        JSON string with complexity metrics
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        results = {}

        # Cyclomatic complexity
        cmd = f"radon cc {shlex.quote(str(scan_path))} -j -a"
        proc = _run_shell(cmd, timeout=60)

        if proc.returncode == 127:
            return json.dumps({
                "error": "radon not installed",
                "install": "pip install radon"
            })

        try:
            cc_data = json.loads(proc.stdout) if proc.stdout else {}
            results["cyclomatic_complexity"] = cc_data

            # Count complexity levels
            complexity_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
            for file_funcs in cc_data.values():
                for func in file_funcs:
                    rank = func.get("rank", "A")
                    if rank in complexity_counts:
                        complexity_counts[rank] += 1

            results["complexity_distribution"] = complexity_counts
        except Exception:
            pass

        # Maintainability index
        cmd = f"radon mi {shlex.quote(str(scan_path))} -j"
        proc = _run_shell(cmd, timeout=60)

        try:
            mi_data = json.loads(proc.stdout) if proc.stdout else {}
            results["maintainability_index"] = mi_data

            # Find low maintainability files
            low_mi = []
            for file_path, mi_info in mi_data.items():
                mi_score = mi_info.get("mi", 100)
                mi_rank = mi_info.get("rank", "A")
                if mi_rank in ["C", "D", "E", "F"]:
                    low_mi.append({
                        "file": file_path,
                        "score": mi_score,
                        "rank": mi_rank
                    })

            results["low_maintainability_files"] = low_mi
        except Exception:
            pass

        # Raw metrics
        cmd = f"radon raw {shlex.quote(str(scan_path))} -j"
        proc = _run_shell(cmd, timeout=60)

        try:
            raw_data = json.loads(proc.stdout) if proc.stdout else {}
            results["raw_metrics"] = raw_data

            # Total metrics
            total_loc = sum(m.get("loc", 0) for m in raw_data.values())
            total_sloc = sum(m.get("sloc", 0) for m in raw_data.values())
            total_comments = sum(m.get("comments", 0) for m in raw_data.values())

            results["totals"] = {
                "lines_of_code": total_loc,
                "source_lines": total_sloc,
                "comments": total_comments,
                "files": len(raw_data)
            }
        except Exception:
            pass

        return json.dumps({
            "tool": "radon",
            "scanned": str(scan_path.relative_to(ROOT)),
            "results": results
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Radon analysis failed: {type(e).__name__}: {e}"})


def find_dead_code(path: str = ".") -> str:
    """Find dead/unused code using vulture.

    Detects:
    - Unused functions and classes
    - Unused variables
    - Unused imports
    - Unreachable code

    Args:
        path: Path to analyze

    Returns:
        JSON string with dead code findings
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        # Run vulture
        cmd = f"vulture {shlex.quote(str(scan_path))} --min-confidence 80"
        proc = _run_shell(cmd, timeout=120)

        if proc.returncode == 127:
            return json.dumps({
                "error": "vulture not installed",
                "install": "pip install vulture"
            })

        # Parse vulture output
        findings = []
        if proc.stdout:
            for line in proc.stdout.splitlines():
                if line.strip():
                    # Format: file.py:123: unused function 'foo' (80% confidence)
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        confidence = 80
                        message = parts[2].strip()

                        # Extract confidence
                        if "(" in message and "%" in message:
                            try:
                                conf_str = message.split("(")[1].split("%")[0]
                                confidence = int(conf_str)
                            except Exception:
                                pass

                        findings.append({
                            "file": parts[0].strip(),
                            "line": parts[1].strip(),
                            "message": message,
                            "confidence": confidence
                        })

        # Categorize findings
        by_type = {
            "unused_function": [],
            "unused_class": [],
            "unused_variable": [],
            "unused_import": [],
            "unused_property": [],
            "unused_attribute": [],
            "other": []
        }

        for finding in findings:
            msg = finding["message"].lower()
            if "function" in msg:
                by_type["unused_function"].append(finding)
            elif "class" in msg:
                by_type["unused_class"].append(finding)
            elif "variable" in msg:
                by_type["unused_variable"].append(finding)
            elif "import" in msg:
                by_type["unused_import"].append(finding)
            elif "property" in msg:
                by_type["unused_property"].append(finding)
            elif "attribute" in msg:
                by_type["unused_attribute"].append(finding)
            else:
                by_type["other"].append(finding)

        return json.dumps({
            "tool": "vulture",
            "scanned": str(scan_path.relative_to(ROOT)),
            "total_findings": len(findings),
            "by_type": {k: len(v) for k, v in by_type.items() if v},
            "findings": findings,
            "details_by_type": {k: v for k, v in by_type.items() if v}
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Dead code detection failed: {type(e).__name__}: {e}"})


def analyze_code_structures(path: str = ".") -> str:
    """Analyze code structures across multiple file types and languages.

    Detects structures in:
    - Database schemas: Prisma (.prisma), SQL (.sql), MongoDB
    - TypeScript/JavaScript: interfaces, types, enums, classes
    - Python: classes, dataclasses, TypedDict, Enum
    - C/C++: struct, typedef, enum
    - Configuration: config files, environment variables
    - Documentation: README structure, API docs

    Returns comprehensive analysis to prevent duplicate definitions.

    Args:
        path: Path to file or directory to analyze

    Returns:
        JSON string with structure analysis
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        # Find relevant structure files
        structure_files = {
            'prisma': [],
            'typescript': [],
            'python': [],
            'c_cpp': [],
            'sql': [],
            'config': [],
            'docs': []
        }

        if scan_path.is_file():
            # Single file analysis
            suffix = scan_path.suffix
            if suffix == '.prisma':
                structure_files['prisma'].append(scan_path)
            elif suffix in ['.ts', '.tsx', '.js', '.jsx']:
                structure_files['typescript'].append(scan_path)
            elif suffix == '.py':
                structure_files['python'].append(scan_path)
            elif suffix in ['.c', '.cpp', '.h', '.hpp', '.cc']:
                structure_files['c_cpp'].append(scan_path)
            elif suffix == '.sql':
                structure_files['sql'].append(scan_path)
            elif scan_path.name in ['README.md', 'README', 'DOCUMENTATION.md']:
                structure_files['docs'].append(scan_path)
            elif 'config' in scan_path.name.lower() or '.env' in scan_path.name:
                structure_files['config'].append(scan_path)
        else:
            # Directory analysis - search for multiple file types
            structure_files['prisma'].extend(list(scan_path.rglob('*.prisma')))
            structure_files['typescript'].extend(list(scan_path.rglob('*.ts')))
            structure_files['typescript'].extend(list(scan_path.rglob('*.tsx')))
            structure_files['python'].extend(list(scan_path.rglob('*.py')))
            structure_files['c_cpp'].extend(list(scan_path.rglob('*.c')))
            structure_files['c_cpp'].extend(list(scan_path.rglob('*.cpp')))
            structure_files['c_cpp'].extend(list(scan_path.rglob('*.h')))
            structure_files['c_cpp'].extend(list(scan_path.rglob('*.hpp')))
            structure_files['sql'].extend(list(scan_path.rglob('*.sql')))
            structure_files['docs'].extend(list(scan_path.rglob('README*')))
            structure_files['docs'].extend(list(scan_path.rglob('DOCUMENTATION*')))
            structure_files['config'].extend(list(scan_path.rglob('config.*')))
            structure_files['config'].extend(list(scan_path.rglob('.env*')))

        total_files = sum(len(files) for files in structure_files.values())
        if total_files == 0:
            return json.dumps({"error": "No structure files found"})

        results: Dict[str, Any] = {
            "files_analyzed": {k: len(v) for k, v in structure_files.items() if v},
            "enums": [],
            "classes": [],
            "interfaces": [],
            "types": [],
            "structs": [],
            "typedefs": [],
            "models": [],
            "tables": [],
            "configs": [],
            "docs": []
        }

        import re

        # Process Prisma files
        for file in structure_files['prisma']:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                rel_path = str(file.relative_to(ROOT))

                # Parse Prisma enums
                for match in re.finditer(r'enum\s+(\w+)\s*\{([^}]+)\}', content):
                    results["enums"].append({
                        "name": match.group(1),
                        "values": [v.strip() for v in match.group(2).strip().split('\n') if v.strip()],
                        "file": rel_path,
                        "language": "prisma",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse Prisma models
                for match in re.finditer(r'model\s+(\w+)\s*\{([^}]+)\}', content):
                    results["models"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "prisma",
                        "line": content[:match.start()].count('\n') + 1
                    })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": rel_path,
                    "error": f"Prisma parse error: {e}"
                })

        # Process TypeScript/JavaScript files
        for file in structure_files['typescript']:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                rel_path = str(file.relative_to(ROOT))

                # Parse TS enums
                for match in re.finditer(r'enum\s+(\w+)\s*\{', content):
                    results["enums"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "typescript",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse TS interfaces
                for match in re.finditer(r'interface\s+(\w+)', content):
                    results["interfaces"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "typescript",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse TS types
                for match in re.finditer(r'type\s+(\w+)\s*=', content):
                    results["types"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "typescript",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse TS/JS classes
                for match in re.finditer(r'class\s+(\w+)', content):
                    results["classes"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "typescript",
                        "line": content[:match.start()].count('\n') + 1
                    })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": rel_path,
                    "error": f"TypeScript parse error: {e}"
                })

        # Process Python files
        for file in structure_files['python']:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                rel_path = str(file.relative_to(ROOT))

                # Parse Python classes
                for match in re.finditer(r'class\s+(\w+)', content):
                    results["classes"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "python",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse Python Enums
                for match in re.finditer(r'class\s+(\w+)\(Enum\)', content):
                    results["enums"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "python",
                        "line": content[:match.start()].count('\n') + 1
                    })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": rel_path,
                    "error": f"Python parse error: {e}"
                })

        # Process C/C++ files
        for file in structure_files['c_cpp']:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                rel_path = str(file.relative_to(ROOT))

                # Parse C/C++ structs
                for match in re.finditer(r'struct\s+(\w+)', content):
                    results["structs"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "c/c++",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse C/C++ typedefs
                for match in re.finditer(r'typedef\s+.*?\s+(\w+);', content):
                    results["typedefs"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "c/c++",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse C/C++ enums
                for match in re.finditer(r'enum\s+(\w+)', content):
                    results["enums"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "c/c++",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse C++ classes
                for match in re.finditer(r'class\s+(\w+)', content):
                    results["classes"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "c++",
                        "line": content[:match.start()].count('\n') + 1
                    })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": rel_path,
                    "error": f"C/C++ parse error: {e}"
                })

        # Process SQL files
        for file in structure_files['sql']:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                rel_path = str(file.relative_to(ROOT))

                # Parse SQL tables
                for match in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)', content, re.IGNORECASE):
                    results["tables"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "sql",
                        "line": content[:match.start()].count('\n') + 1
                    })

                # Parse SQL enums (PostgreSQL syntax)
                for match in re.finditer(r'CREATE\s+TYPE\s+(\w+)\s+AS\s+ENUM', content, re.IGNORECASE):
                    results["enums"].append({
                        "name": match.group(1),
                        "file": rel_path,
                        "language": "sql",
                        "line": content[:match.start()].count('\n') + 1
                    })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": rel_path,
                    "error": f"SQL parse error: {e}"
                })

        # Process config files
        for file in structure_files['config']:
            try:
                rel_path = str(file.relative_to(ROOT))
                results["configs"].append({
                    "name": file.name,
                    "file": rel_path,
                    "type": "config"
                })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": str(file),
                    "error": f"Config parse error: {e}"
                })

        # Process documentation files
        for file in structure_files['docs']:
            try:
                rel_path = str(file.relative_to(ROOT))
                results["docs"].append({
                    "name": file.name,
                    "file": rel_path,
                    "type": "documentation"
                })
            except Exception as e:
                results.setdefault("errors", []).append({
                    "file": str(file),
                    "error": f"Docs parse error: {e}"
                })

        # Summary
        results["summary"] = {
            "total_files": total_files,
            "total_enums": len(results["enums"]),
            "total_classes": len(results["classes"]),
            "total_interfaces": len(results["interfaces"]),
            "total_types": len(results["types"]),
            "total_structs": len(results["structs"]),
            "total_typedefs": len(results["typedefs"]),
            "total_models": len(results["models"]),
            "total_tables": len(results["tables"]),
            "total_configs": len(results["configs"]),
            "total_docs": len(results["docs"]),
            "enum_names": sorted(set(e["name"] for e in results["enums"])),
            "class_names": sorted(set(c["name"] for c in results["classes"])),
            "interface_names": sorted(set(i["name"] for i in results["interfaces"])),
            "type_names": sorted(set(t["name"] for t in results["types"])),
            "struct_names": sorted(set(s["name"] for s in results["structs"])),
            "typedef_names": sorted(set(t["name"] for t in results["typedefs"])),
            "model_names": sorted(set(m["name"] for m in results["models"])),
            "table_names": sorted(set(t["name"] for t in results["tables"]))
        }

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Code structure analysis failed: {type(e).__name__}: {e}"})


def run_all_analysis(path: str = ".") -> str:
    """Run all available analysis tools and combine results.

    Args:
        path: Path to analyze

    Returns:
        JSON string with combined analysis results
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        results = {
            "scanned": str(scan_path.relative_to(ROOT)),
            "tools_run": []
        }

        # AST analysis
        try:
            ast_result = json.loads(analyze_ast_patterns(str(scan_path)))
            if "error" not in ast_result:
                results["ast_analysis"] = ast_result
                results["tools_run"].append("ast")
        except Exception:
            pass

        # Pylint
        try:
            pylint_result = json.loads(run_pylint(str(scan_path)))
            if "error" not in pylint_result:
                results["pylint"] = pylint_result
                results["tools_run"].append("pylint")
        except Exception:
            pass

        # Mypy
        try:
            mypy_result = json.loads(run_mypy(str(scan_path)))
            if "error" not in mypy_result:
                results["mypy"] = mypy_result
                results["tools_run"].append("mypy")
        except Exception:
            pass

        # Radon
        try:
            radon_result = json.loads(run_radon_complexity(str(scan_path)))
            if "error" not in radon_result:
                results["radon"] = radon_result
                results["tools_run"].append("radon")
        except Exception:
            pass

        # Vulture
        try:
            vulture_result = json.loads(find_dead_code(str(scan_path)))
            if "error" not in vulture_result:
                results["vulture"] = vulture_result
                results["tools_run"].append("vulture")
        except Exception:
            pass

        # Summary
        total_issues = 0
        if "ast_analysis" in results:
            total_issues += results["ast_analysis"].get("total_issues", 0)
        if "pylint" in results:
            total_issues += results["pylint"].get("total_issues", 0)
        if "mypy" in results:
            total_issues += results["mypy"].get("total_issues", 0)
        if "vulture" in results:
            total_issues += results["vulture"].get("total_findings", 0)

        results["summary"] = {
            "total_tools": len(results["tools_run"]),
            "total_issues_found": total_issues,
            "tools_available": results["tools_run"]
        }

        return json.dumps(results, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Combined analysis failed: {type(e).__name__}: {e}"})
