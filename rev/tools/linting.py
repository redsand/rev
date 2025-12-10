#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregated linting and type-check tools across languages."""

import json
import re
import shlex
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from rev.config import ROOT
from rev.tools.utils import _run_shell, _safe_path
from rev.tools.analysis import analyze_static_types


def _resolve_paths(paths: Optional[List[str]]) -> Tuple[List[Path], List[str]]:
    resolved: List[Path] = []
    missing: List[str] = []
    for p in paths or ["."]:
        try:
            rp = _safe_path(p)
            if rp.exists():
                resolved.append(rp)
            else:
                missing.append(p)
        except Exception:
            missing.append(p)
    return resolved, missing


def _has_files(resolved_paths: List[Path], suffixes: List[str]) -> bool:
    for p in resolved_paths:
        if p.is_file():
            if p.suffix.lower() in suffixes:
                return True
        else:
            for suf in suffixes:
                if next(p.rglob(f"*{suf}"), None):
                    return True
    return False


def _run_and_parse(cmd: str, parser, timeout: int = 300) -> Tuple[int, List[Dict[str, Any]], Optional[str]]:
    proc = _run_shell(cmd, timeout=timeout)
    if proc.returncode == 127:
        return proc.returncode, [], "not_installed"
    issues = []
    try:
        issues = parser(proc.stdout)
    except Exception:
        pass
    return proc.returncode, issues, None


def _parse_ruff(stdout: str) -> List[Dict[str, Any]]:
    results = json.loads(stdout) if stdout else []
    issues = []
    for item in results:
        loc = item.get("location", {})
        issues.append({
            "file": item.get("filename") or item.get("file") or loc.get("path"),
            "line": loc.get("row") or loc.get("line"),
            "column": loc.get("column"),
            "rule": item.get("code"),
            "message": item.get("message"),
            "severity": "warning",
            "tool": "ruff"
        })
    return issues


def _parse_flake8(stdout: str) -> List[Dict[str, Any]]:
    issues = []
    for line in stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) >= 4:
            issues.append({
                "file": parts[0].strip(),
                "line": int(parts[1]),
                "column": int(parts[2]),
                "rule": parts[3].strip().split()[0] if parts[3].strip() else "",
                "message": parts[3].strip(),
                "severity": "warning",
                "tool": "flake8"
            })
    return issues


def _parse_eslint(stdout: str) -> List[Dict[str, Any]]:
    data = json.loads(stdout) if stdout else []
    issues: List[Dict[str, Any]] = []
    for file_result in data:
        file_path = file_result.get("filePath")
        for msg in file_result.get("messages", []):
            issues.append({
                "file": file_path,
                "line": msg.get("line"),
                "column": msg.get("column"),
                "rule": msg.get("ruleId"),
                "message": msg.get("message"),
                "severity": "error" if msg.get("severity") == 2 else "warning",
                "tool": "eslint"
            })
    return issues


def _parse_golangci(stdout: str) -> List[Dict[str, Any]]:
    data = json.loads(stdout) if stdout else {}
    issues: List[Dict[str, Any]] = []
    for issue in data.get("Issues", []):
        issues.append({
            "file": issue.get("Pos", {}).get("Filename") or issue.get("Pos", {}).get("file"),
            "line": issue.get("Pos", {}).get("Line") or issue.get("pos", {}).get("line"),
            "column": issue.get("Pos", {}).get("Column"),
            "rule": issue.get("FromLinter") or issue.get("from_linter"),
            "message": issue.get("Text") or issue.get("text"),
            "severity": "warning",
            "tool": "golangci-lint"
        })
    return issues


def _parse_pyright(stdout: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    pattern = re.compile(r"^(.*?):(\d+):(\d+):\s*(error|warning)\s*(\[[A-Za-z0-9-]+\])?:?\s*(.*)")
    for line in stdout.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        file_path, line_no, col_no, sev, code, msg = m.groups()
        issues.append({
            "file": file_path,
            "line": int(line_no),
            "column": int(col_no),
            "rule": code.strip("[]") if code else None,
            "message": msg.strip(),
            "severity": "error" if sev.lower() == "error" else "warning",
            "tool": "pyright"
        })
    return issues


def _parse_tsc(stdout: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    pattern = re.compile(r"^(.*?)(?:\((\d+),(\d+)\))?:\s*(error|warning)\s*TS(\d+):\s*(.*)")
    for line in stdout.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        file_path, line_no, col_no, sev, code, msg = m.groups()
        issues.append({
            "file": file_path,
            "line": int(line_no) if line_no else None,
            "column": int(col_no) if col_no else None,
            "rule": f"TS{code}",
            "message": msg.strip(),
            "severity": "error" if sev.lower() == "error" else "warning",
            "tool": "tsc"
        })
    return issues


def run_linters(paths: Optional[List[str]] = None) -> str:
    """Aggregate linters across languages (Python, JS/TS, Go)."""
    try:
        resolved_paths, missing = _resolve_paths(paths)
        if not resolved_paths:
            return json.dumps({"error": "No valid paths to lint", "missing_paths": missing})

        python_found = _has_files(resolved_paths, [".py"]) or (ROOT / "pyproject.toml").exists()
        js_ts_found = _has_files(resolved_paths, [".js", ".ts", ".jsx", ".tsx"]) or (ROOT / "package.json").exists()
        go_found = _has_files(resolved_paths, [".go"]) or (ROOT / "go.mod").exists()

        issues: List[Dict[str, Any]] = []
        summary_tools: Dict[str, Dict[str, Any]] = {}
        exit_code = 0
        cmd_missing: List[str] = []

        joined_paths = " ".join(shlex.quote(str(p)) for p in resolved_paths)

        if python_found:
            rc, py_issues, status = _run_and_parse(f"ruff check {joined_paths} --output-format json", _parse_ruff)
            if status == "not_installed":
                rc, py_issues, status = _run_and_parse(f"flake8 {joined_paths}", _parse_flake8)
            if status == "not_installed":
                cmd_missing.append("ruff/flake8")
            else:
                exit_code = max(exit_code, rc)
                issues.extend(py_issues)
                summary_tools["python"] = {"tool": "ruff" if py_issues else "ruff/flake8", "issues": len(py_issues), "returncode": rc}

        if js_ts_found:
            rc, js_issues, status = _run_and_parse(f"npx eslint --format json --max-warnings=0 {joined_paths}", _parse_eslint, timeout=400)
            if status == "not_installed":
                cmd_missing.append("eslint")
            else:
                exit_code = max(exit_code, rc)
                issues.extend(js_issues)
                summary_tools["javascript"] = {"tool": "eslint", "issues": len(js_issues), "returncode": rc}

        if go_found:
            rc, go_issues, status = _run_and_parse(f"golangci-lint run --out-format json {joined_paths}", _parse_golangci, timeout=400)
            if status == "not_installed":
                cmd_missing.append("golangci-lint")
            else:
                exit_code = max(exit_code, rc)
                issues.extend(go_issues)
                summary_tools["go"] = {"tool": "golangci-lint", "issues": len(go_issues), "returncode": rc}

        if not summary_tools and cmd_missing:
            return json.dumps({"error": "No linters available", "missing_tools": cmd_missing, "missing_paths": missing})

        by_tool: Dict[str, int] = {}
        for issue in issues:
            tool = issue.get("tool", "unknown")
            by_tool[tool] = by_tool.get(tool, 0) + 1

        return json.dumps({
            "exit_code": exit_code,
            "issues": issues,
            "summary": {
                "by_tool": by_tool,
                "tools_run": summary_tools,
                "missing_tools": cmd_missing,
                "missing_paths": missing
            }
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Linter execution failed: {type(e).__name__}: {e}"})


def run_type_checks(paths: Optional[List[str]] = None) -> str:
    """Run type checkers across languages (mypy/pyright/tsc)."""
    try:
        resolved_paths, missing = _resolve_paths(paths)
        if not resolved_paths:
            return json.dumps({"error": "No valid paths to type-check", "missing_paths": missing})

        issues: List[Dict[str, Any]] = []
        summary: Dict[str, Any] = {"tools_run": [], "missing_tools": [], "missing_paths": missing}
        exit_code = 0
        joined_paths = " ".join(shlex.quote(str(p)) for p in resolved_paths)

        # Python: mypy (only if config present)
        mypy_configs = ["mypy.ini", "pyproject.toml", "setup.cfg"]
        has_mypy_config = any((ROOT / cfg).exists() for cfg in mypy_configs)
        if has_mypy_config:
            mypy_result = analyze_static_types(paths=[str(p) for p in resolved_paths], config_file="mypy.ini", strict=False)
            try:
                parsed = json.loads(mypy_result)
                mypy_issues = parsed.get("issues", [])
                issues.extend([{**i, "tool": "mypy"} for i in mypy_issues])
                exit_code = max(exit_code, 1 if mypy_issues else 0)
                summary["tools_run"].append({"tool": "mypy", "issues": len(mypy_issues)})
            except Exception:
                summary["tools_run"].append({"tool": "mypy", "issues": "parse_error"})
        else:
            summary["missing_tools"].append("mypy (no config)")

        # Python: pyright
        pyright_config = (ROOT / "pyrightconfig.json")
        if pyright_config.exists():
            rc, pyright_issues, status = _run_and_parse(f"pyright {joined_paths}", _parse_pyright, timeout=400)
            if status == "not_installed":
                summary["missing_tools"].append("pyright")
            else:
                exit_code = max(exit_code, rc)
                issues.extend(pyright_issues)
                summary["tools_run"].append({"tool": "pyright", "issues": len(pyright_issues), "returncode": rc})

        # TypeScript: tsc --noEmit
        tsconfig = ROOT / "tsconfig.json"
        if tsconfig.exists():
            rc, tsc_issues, status = _run_and_parse(f"tsc --noEmit", _parse_tsc, timeout=400)
            if status == "not_installed":
                summary["missing_tools"].append("tsc")
            else:
                exit_code = max(exit_code, rc)
                issues.extend(tsc_issues)
                summary["tools_run"].append({"tool": "tsc", "issues": len(tsc_issues), "returncode": rc})

        if not summary["tools_run"]:
            return json.dumps({"error": "No type checkers executed", "missing_tools": summary["missing_tools"], "missing_paths": missing})

        by_tool: Dict[str, int] = {}
        for issue in issues:
            tool = issue.get("tool", "unknown")
            by_tool[tool] = by_tool.get(tool, 0) + 1

        summary["by_tool"] = by_tool
        summary["exit_code"] = exit_code

        return json.dumps({"issues": issues, "summary": summary}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Type checking failed: {type(e).__name__}: {e}"})
