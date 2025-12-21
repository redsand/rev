#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dependency management and analysis utilities."""

import json
from typing import Dict, Any, Optional, List

from rev import config
from rev.tools.utils import _run_shell
try:
    from packaging.version import Version, InvalidVersion
except ImportError:  # pragma: no cover
    Version = None
    InvalidVersion = Exception

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
    # Configuration for different languages
    lang_config = {
        "python": {"file": "requirements.txt", "alt_file": "pyproject.toml"},
        "javascript": {"file": "package.json"},
        "rust": {"file": "Cargo.toml"},
        "go": {"file": "go.mod"},
    }

    try:
        if language == "auto":
            for lang, cfg in lang_config.items():
                if (config.ROOT / cfg["file"]).exists() or (
                    cfg.get("alt_file") and (config.ROOT / cfg["alt_file"]).exists()
                ):
                    language = lang
                    break
        
        if language not in lang_config:
            return json.dumps({"error": f"Language '{language}' not supported"})

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
            req_file = config.ROOT / lang_config["python"]["file"]
            if req_file.exists():
                content = req_file.read_text(encoding='utf-8')
                deps = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#')]
                result["dependencies"] = deps
                result["count"] = len(deps)
                result["file"] = lang_config["python"]["file"]

                # Check for unpinned versions
                unpinned = [d for d in deps if '==' not in d and '>=' not in d]
                if unpinned:
                    result["issues"].append({
                        "type": "unpinned_versions",
                        "count": len(unpinned),
                        "packages": unpinned[:10]
                    })

            # Check for virtual environment
            if not (config.ROOT / "venv").exists() and not (config.ROOT / ".venv").exists():
                result["issues"].append({
                    "type": "no_virtual_environment",
                    "message": "No virtual environment detected"
                })

        elif language == "javascript":
            pkg_file = config.ROOT / lang_config["javascript"]["file"]
            if pkg_file.exists():
                pkg_data = json.loads(pkg_file.read_text(encoding='utf-8'))
                deps = pkg_data.get("dependencies", {})
                dev_deps = pkg_data.get("devDependencies", {})

                result["dependencies"] = list(deps.keys())
                result["dev_dependencies"] = list(dev_deps.keys())
                result["count"] = len(deps) + len(dev_deps)
                result["file"] = lang_config["javascript"]["file"]

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


def check_dependency_updates(language: str = "auto") -> str:
    """Identify outdated dependencies grouped by potential impact."""
    lang_config = {
        "python": {"file": "requirements.txt", "alt_file": "pyproject.toml", "command": "pip list --outdated --format=json"},
        "javascript": {"file": "package.json", "command": "npm outdated --json"},
    }

    try:
        if language == "auto":
            for lang, cfg in lang_config.items():
                if (config.ROOT / cfg["file"]).exists() or (
                    cfg.get("alt_file") and (config.ROOT / cfg["alt_file"]).exists()
                ):
                    language = lang
                    break

        if language not in lang_config:
            return json.dumps({"error": f"Language '{language}' not supported"})

        proc = _run_shell(lang_config[language]["command"], timeout=120)
        if proc.returncode == 127:
            return json.dumps({"error": f"{lang_config[language]['command'].split()[0]} not available"})

        if language == "python":
            outdated = json.loads(proc.stdout) if proc.stdout else []
            grouped = _group_versions(outdated, "name", "version", "latest_version")
            return json.dumps({
                "language": "python",
                "updates": grouped,
                "count": sum(len(v) for v in grouped.values())
            }, indent=2)

        if language == "javascript":
            data = json.loads(proc.stdout) if proc.stdout else {}
            items = []
            for pkg, info in data.items():
                items.append({
                    "name": pkg,
                    "version": info.get("current"),
                    "latest_version": info.get("latest")
                })
            grouped = _group_versions(items, "name", "version", "latest_version")
            return json.dumps({
                "language": "javascript",
                "updates": grouped,
                "count": sum(len(v) for v in grouped.values())
            }, indent=2)

        return json.dumps({"error": f"Language '{language}' not supported"})

    except Exception as e:
        return json.dumps({"error": f"Update check failed: {type(e).__name__}: {e}"})


def check_dependency_vulnerabilities(language: str = "auto") -> str:
    """Scan dependencies for known vulnerabilities using pip-audit or npm audit."""
    lang_config = {
        "python": {"file": "requirements.txt", "alt_file": "pyproject.toml", "command": "pip-audit -f json"},
        "javascript": {"file": "package.json", "command": "npm audit --json"},
    }

    try:
        if language == "auto":
            for lang, cfg in lang_config.items():
                if (config.ROOT / cfg["file"]).exists() or (
                    cfg.get("alt_file") and (config.ROOT / cfg["alt_file"]).exists()
                ):
                    language = lang
                    break

        if language not in lang_config:
            return json.dumps({"error": f"Language '{language}' not supported"})

        cmd = lang_config[language]["command"]
        if language == "python" and (config.ROOT / "requirements.txt").exists():
            cmd = "pip-audit -r requirements.txt -f json"

        proc = _run_shell(cmd, timeout=180)
        if proc.returncode == 127:
            tool_name = "pip-audit" if language == "python" else "npm"
            return json.dumps({"error": f"{tool_name} not available", "install": f"pip install {tool_name}" if language == "python" else ""})

        if language == "python":
            try:
                findings = json.loads(proc.stdout) if proc.stdout else []
            except json.JSONDecodeError:
                findings = []
                
            if not isinstance(findings, list):
                findings = []
                
            issues = []
            for f in findings:
                if not isinstance(f, dict):
                    continue
                dep = f.get("dependency", {})
                for vuln in f.get("vulns", []):
                    issues.append({
                        "package": dep.get("name"),
                        "version": dep.get("version"),
                        "severity": vuln.get("severity") or vuln.get("severity_source"),
                        "cves": vuln.get("id"),
                        "fixed_version": (vuln.get("fix_versions") or [None])[0],
                        "description": vuln.get("description", "")[:500]
                    })
            return json.dumps({
                "language": "python",
                "issues": issues,
                "tool": "pip-audit",
                "count": len(issues)
            }, indent=2)

        if language == "javascript":
            try:
                audit = json.loads(proc.stdout) if proc.stdout else {}
            except json.JSONDecodeError:
                audit = {}
            
            if not isinstance(audit, dict):
                audit = {}
                
            issues = []
            advisories = audit.get("advisories")
            if isinstance(advisories, dict):
                for advisory in advisories.values():
                    issues.append({
                        "package": advisory.get("module_name"),
                        "version": advisory.get("findings", [{}])[0].get("version"),
                        "severity": advisory.get("severity"),
                        "cves": advisory.get("cves"),
                        "fixed_version": advisory.get("patched_versions"),
                        "description": advisory.get("title", "")
                    })
            elif isinstance(audit.get("metadata"), dict):
                # Handle newer npm audit format (v7+)
                for vuln in audit.get("vulnerabilities", {}).values():
                    issues.append({
                        "package": vuln.get("name"),
                        "version": vuln.get("range"),
                        "severity": vuln.get("severity"),
                        "cves": [], # v7+ format differs
                        "fixed_version": None,
                        "description": f"Vulnerability in {vuln.get('name')}"
                    })
            return json.dumps({
                "language": "javascript",
                "issues": issues,
                "tool": "npm audit",
                "count": len(issues)
            }, indent=2)

        return json.dumps({
            "language": language,
            "error": f"Language '{language}' not supported"
        })

    except Exception as e:
        return json.dumps({
            "language": language,
            "error": f"Dependency vulnerability scan failed: {type(e).__name__}: {e}"
        })


def _group_versions(items: List[Dict[str, Any]], name_key: str, current_key: str, latest_key: str) -> Dict[str, List[Dict[str, Any]]]:
    groups = {"breaking": [], "minor": [], "patch": []}
    for item in items:
        name = item.get(name_key)
        current = item.get(current_key)
        latest = item.get(latest_key)
        if not Version:
            groups["patch"].append({"package": name, "current": current, "latest": latest})
            continue
        try:
            cur_v = Version(str(current))
            lat_v = Version(str(latest))
        except (InvalidVersion, TypeError):
            groups["patch"].append({"package": name, "current": current, "latest": latest})
            continue

        bucket = "patch"
        if lat_v.major > cur_v.major:
            bucket = "breaking"
        elif lat_v.minor > cur_v.minor:
            bucket = "minor"

        groups[bucket].append({"package": name, "current": current, "latest": latest})
    return groups


# Backward-compatible wrappers
def update_dependencies(language: str = "auto", major: bool = False) -> str:
    """Legacy wrapper for check_dependency_updates."""
    return check_dependency_updates(language)


def scan_dependencies_vulnerabilities(language: str = "auto") -> str:
    """Legacy wrapper for check_dependency_vulnerabilities."""
    return check_dependency_vulnerabilities(language)
