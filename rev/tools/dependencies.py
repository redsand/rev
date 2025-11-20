#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dependency management and analysis utilities."""

import json
from typing import Dict, Any, Optional

from rev.config import ROOT
from rev.tools.utils import _run_shell

# Note: This module uses a dependency cache that should be initialized elsewhere
# For now, we'll create a simple cache interface
_DEP_CACHE = None


def _get_dep_cache():
    """Get or create dependency cache instance."""
    global _DEP_CACHE
    if _DEP_CACHE is None:
        # This will be set by the main module
        # For standalone use, we'll skip caching
        return None
    return _DEP_CACHE


def set_dep_cache(cache):
    """Set the dependency cache instance."""
    global _DEP_CACHE
    _DEP_CACHE = cache


def analyze_dependencies(language: str = "auto") -> str:
    """Analyze project dependencies and check for issues.

    Args:
        language: Language/ecosystem (python, javascript, auto)

    Returns:
        JSON string with dependency analysis
    """
    try:
        if language == "auto":
            # Auto-detect from project files
            if (ROOT / "requirements.txt").exists() or (ROOT / "pyproject.toml").exists():
                language = "python"
            elif (ROOT / "package.json").exists():
                language = "javascript"
            elif (ROOT / "Cargo.toml").exists():
                language = "rust"
            elif (ROOT / "go.mod").exists():
                language = "go"

        # Try to get from cache first
        cache = _get_dep_cache()
        if cache is not None:
            cached_result = cache.get_dependencies(language)
            if cached_result is not None:
                return cached_result

        result: Dict[str, Any] = {
            "language": language,
            "dependencies": [],
            "issues": []
        }

        if language == "python":
            # Check requirements.txt
            req_file = ROOT / "requirements.txt"
            if req_file.exists():
                content = req_file.read_text(encoding='utf-8')
                deps = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
                result["dependencies"] = deps
                result["count"] = len(deps)
                result["file"] = "requirements.txt"

                # Check for unpinned versions
                unpinned = [d for d in deps if '==' not in d and '>=' not in d]
                if unpinned:
                    result["issues"].append({
                        "type": "unpinned_versions",
                        "count": len(unpinned),
                        "packages": unpinned[:10]
                    })

            # Check for virtual environment
            if not (ROOT / "venv").exists() and not (ROOT / ".venv").exists():
                result["issues"].append({
                    "type": "no_virtual_environment",
                    "message": "No virtual environment detected"
                })

        elif language == "javascript":
            pkg_file = ROOT / "package.json"
            if pkg_file.exists():
                pkg_data = json.loads(pkg_file.read_text(encoding='utf-8'))
                deps = pkg_data.get("dependencies", {})
                dev_deps = pkg_data.get("devDependencies", {})

                result["dependencies"] = list(deps.keys())
                result["dev_dependencies"] = list(dev_deps.keys())
                result["count"] = len(deps) + len(dev_deps)
                result["file"] = "package.json"

                # Check for caret/tilde versions
                risky_versions = []
                for pkg, ver in {**deps, **dev_deps}.items():
                    if ver.startswith('^') or ver.startswith('~'):
                        risky_versions.append(f"{pkg}@{ver}")

                if risky_versions:
                    result["issues"].append({
                        "type": "flexible_versions",
                        "count": len(risky_versions),
                        "message": "Using ^ or ~ version ranges",
                        "packages": risky_versions[:10]
                    })

        # Cache the result
        result_json = json.dumps(result)
        cache = _get_dep_cache()
        if cache is not None:
            cache.set_dependencies(language, result_json)

        return result_json

    except Exception as e:
        return json.dumps({"error": f"Analysis failed: {type(e).__name__}: {e}"})


def update_dependencies(language: str = "auto", major: bool = False) -> str:
    """Update project dependencies to latest versions.

    Args:
        language: Language/ecosystem (python, javascript, auto)
        major: Allow major version updates (default: False)

    Returns:
        JSON string with update results
    """
    try:
        if language == "auto":
            if (ROOT / "requirements.txt").exists():
                language = "python"
            elif (ROOT / "package.json").exists():
                language = "javascript"

        if language == "python":
            # Update using pip-upgrader or similar
            cmd = "pip list --outdated --format=json"
            result = _run_shell(cmd)

            if result.returncode == 0:
                outdated = json.loads(result.stdout) if result.stdout else []
                return json.dumps({
                    "language": "python",
                    "outdated": outdated,
                    "count": len(outdated),
                    "message": "Use 'pip install --upgrade <package>' to update"
                })
            else:
                return json.dumps({"error": "Failed to check outdated packages"})

        elif language == "javascript":
            # Check for npm updates
            cmd = "npm outdated --json"
            result = _run_shell(cmd, timeout=60)

            try:
                outdated = json.loads(result.stdout) if result.stdout else {}
                return json.dumps({
                    "language": "javascript",
                    "outdated": outdated,
                    "count": len(outdated),
                    "message": "Use 'npm update' to update dependencies"
                })
            except Exception:
                return json.dumps({
                    "language": "javascript",
                    "message": "No outdated packages found or npm not available"
                })

        return json.dumps({"error": f"Language '{language}' not supported"})

    except Exception as e:
        return json.dumps({"error": f"Update check failed: {type(e).__name__}: {e}"})


def scan_dependencies_vulnerabilities(language: str = "auto") -> str:
    """Scan dependencies for known vulnerabilities.

    Args:
        language: Language/ecosystem (python, javascript, auto)

    Returns:
        JSON string with vulnerability report
    """
    try:
        if language == "auto":
            if (ROOT / "requirements.txt").exists():
                language = "python"
            elif (ROOT / "package.json").exists():
                language = "javascript"

        result: Dict[str, Any] = {
            "language": language,
            "vulnerabilities": [],
            "tool": ""
        }

        if language == "python":
            # Try safety first
            cmd = "safety check --json --file requirements.txt"
            proc = _run_shell(cmd, timeout=60)

            if proc.returncode == 0 or proc.stdout:
                try:
                    safety_data = json.loads(proc.stdout) if proc.stdout else []
                    result["tool"] = "safety"
                    result["vulnerabilities"] = safety_data
                    result["count"] = len(safety_data)
                    return json.dumps(result)
                except Exception:
                    pass

            # Try pip-audit as fallback
            cmd = "pip-audit --format json"
            proc = _run_shell(cmd, timeout=60)

            if proc.returncode == 0 or proc.stdout:
                try:
                    audit_data = json.loads(proc.stdout) if proc.stdout else {"dependencies": []}
                    result["tool"] = "pip-audit"
                    result["vulnerabilities"] = audit_data.get("dependencies", [])
                    result["count"] = len(audit_data.get("dependencies", []))
                    return json.dumps(result)
                except Exception:
                    pass

            return json.dumps({
                "error": "No security scanning tool available",
                "message": "Install safety or pip-audit: pip install safety pip-audit"
            })

        elif language == "javascript":
            # Use npm audit
            cmd = "npm audit --json"
            proc = _run_shell(cmd, timeout=60)

            try:
                audit_data = json.loads(proc.stdout) if proc.stdout else {}
                vulnerabilities = audit_data.get("vulnerabilities", {})

                result["tool"] = "npm audit"
                result["vulnerabilities"] = vulnerabilities
                result["count"] = len(vulnerabilities)
                result["summary"] = audit_data.get("metadata", {})

                return json.dumps(result)
            except Exception:
                return json.dumps({
                    "language": "javascript",
                    "message": "npm audit not available or no vulnerabilities found"
                })

        return json.dumps({"error": f"Language '{language}' not supported"})

    except Exception as e:
        return json.dumps({"error": f"Vulnerability scan failed: {type(e).__name__}: {e}"})
