#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security scanning and analysis utilities."""

import json
import shlex
from pathlib import Path
from typing import Dict, Any, List, Optional

from rev.config import ROOT
from rev.tools.utils import _run_shell, _safe_path


def scan_security_issues(
    paths: Optional[List[str]] = None,
    severity_threshold: str = "MEDIUM"
) -> str:
    """Run security linters (bandit/ruff/semgrep) and return filtered issues."""
    try:
        target_paths = paths or ["."]
        resolved_paths: List[Path] = []
        missing: List[str] = []

        for p in target_paths:
            try:
                resolved = _safe_path(p)
                if resolved.exists():
                    resolved_paths.append(resolved)
                else:
                    missing.append(p)
            except Exception:
                missing.append(p)

        if not resolved_paths:
            return json.dumps({"error": "No valid paths to scan", "missing_paths": missing})

        severity_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        threshold_value = severity_order.get(severity_threshold.upper(), 2)

        issues: List[Dict[str, Any]] = []
        tools_used: List[str] = []

        def _rel_path(path_str: str) -> str:
            try:
                return str(Path(path_str).resolve().relative_to(ROOT))
            except Exception:
                return path_str

        # Bandit scan
        bandit_cmd_parts = ["bandit", "-f", "json"]
        if any(p.is_dir() for p in resolved_paths):
            bandit_cmd_parts.append("-r")
        bandit_cmd_parts.extend(shlex.quote(str(p)) for p in resolved_paths)
        bandit_proc = _run_shell(" ".join(bandit_cmd_parts), timeout=180)

        if bandit_proc.returncode != 127:
            tools_used.append("bandit")
            try:
                bandit_data = json.loads(bandit_proc.stdout) if bandit_proc.stdout else {}
                for finding in bandit_data.get("results", []):
                    severity = str(finding.get("issue_severity", "MEDIUM")).upper()
                    if severity_order.get(severity, 1) < threshold_value:
                        continue
                    issues.append({
                        "file": _rel_path(finding.get("filename", "")),
                        "line": finding.get("line_number"),
                        "code": finding.get("test_id"),
                        "severity": severity,
                        "message": finding.get("issue_text", "").strip(),
                        "fix_hint": finding.get("more_info")
                    })
            except Exception:
                pass

        # Ruff security rules
        ruff_cmd_parts = ["ruff", "check", "--select", "S", "--output-format", "json"]
        ruff_cmd_parts.extend(shlex.quote(str(p)) for p in resolved_paths)
        ruff_proc = _run_shell(" ".join(ruff_cmd_parts), timeout=180)

        if ruff_proc.returncode != 127:
            tools_used.append("ruff")
            try:
                ruff_results = json.loads(ruff_proc.stdout) if ruff_proc.stdout else []
                for finding in ruff_results:
                    code = finding.get("code")
                    location = finding.get("location", finding.get("range", {})) or {}
                    path_hint = location.get("path") or finding.get("filename") or finding.get("file")
                    line = location.get("row") or location.get("line")
                    severity = "MEDIUM"
                    if severity_order.get(severity, 1) < threshold_value:
                        continue
                    issues.append({
                        "file": _rel_path(str(path_hint)) if path_hint else None,
                        "line": line,
                        "code": code,
                        "severity": severity,
                        "message": finding.get("message", ""),
                        "fix_hint": finding.get("url") or finding.get("fix", "")
                    })
            except Exception:
                pass

        # Semgrep auto config (multi-language)
        semgrep_cmd_parts = ["semgrep", "--config=auto", "--json"]
        semgrep_cmd_parts.extend(shlex.quote(str(p)) for p in resolved_paths)
        semgrep_proc = _run_shell(" ".join(semgrep_cmd_parts), timeout=180)

        if semgrep_proc.returncode != 127:
            tools_used.append("semgrep")
            try:
                semgrep_data = json.loads(semgrep_proc.stdout) if semgrep_proc.stdout else {}
                for finding in semgrep_data.get("results", []):
                    severity = str(finding.get("extra", {}).get("severity", "MEDIUM")).upper()
                    if severity_order.get(severity, 1) < threshold_value:
                        continue
                    issue = {
                        "file": _rel_path(finding.get("path", "")),
                        "line": finding.get("start", {}).get("line"),
                        "code": finding.get("check_id"),
                        "severity": severity,
                        "message": finding.get("extra", {}).get("message", ""),
                        "fix_hint": finding.get("extra", {}).get("metadata", {}).get("reference", "")
                    }
                    issues.append(issue)
            except Exception:
                pass

        if not tools_used:
            return json.dumps({
                "error": "No security scanning tools available",
                "install": "pip install bandit ruff"
            })

        by_severity: Dict[str, int] = {}
        for issue in issues:
            sev = (issue.get("severity") or "MEDIUM").upper()
            by_severity[sev] = by_severity.get(sev, 0) + 1

        summary = {
            "paths": [str(p.relative_to(ROOT)) for p in resolved_paths],
            "tools_used": tools_used,
            "severity_threshold": severity_threshold.upper(),
            "issue_count": len(issues),
            "by_severity": by_severity,
            "missing_paths": missing
        }

        return json.dumps({"issues": issues, "summary": summary}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Security issue scan failed: {type(e).__name__}: {e}"})


def detect_secrets(path: str = ".") -> str:
    """Scan for accidentally committed secrets and credentials.

    Args:
        path: Path to scan

    Returns:
        JSON string with detected secrets
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        # Try detect-secrets tool
        cmd = f"detect-secrets scan {shlex.quote(str(scan_path))}"
        proc = _run_shell(cmd, timeout=60)

        if proc.returncode == 127:
            return json.dumps({
                "error": "detect-secrets not installed",
                "message": "Install with: pip install detect-secrets"
            })

        try:
            secrets_data = json.loads(proc.stdout) if proc.stdout else {}
            results = secrets_data.get("results", {})

            # Count total secrets
            total_secrets = sum(len(secrets) for secrets in results.values())

            # Get summary by file
            by_file: Dict[str, int] = {}
            for file_path, secrets in results.items():
                by_file[file_path] = len(secrets)

            return json.dumps({
                "scanned": str(scan_path.relative_to(ROOT)),
                "tool": "detect-secrets",
                "secrets_found": total_secrets,
                "files_with_secrets": len(results),
                "by_file": by_file
            })
        except Exception:
            return json.dumps({
                "scanned": str(scan_path.relative_to(ROOT)),
                "message": "No secrets detected or scan completed successfully"
            })

    except Exception as e:
        return json.dumps({"error": f"Secret detection failed: {type(e).__name__}: {e}"})


def check_license_compliance(path: str = ".") -> str:
    """Check dependency licenses for compliance issues.

    Args:
        path: Project path

    Returns:
        JSON string with license information
    """
    try:
        # Python: Use pip-licenses
        if (ROOT / "requirements.txt").exists():
            cmd = "pip-licenses --format=json"
            proc = _run_shell(cmd, timeout=60)

            if proc.returncode != 127:
                try:
                    licenses = json.loads(proc.stdout) if proc.stdout else []

                    # Flag potentially problematic licenses
                    restricted = ["GPL-3.0", "AGPL-3.0", "GPL-2.0"]
                    issues: List[Dict[str, Any]] = []

                    for pkg in licenses:
                        license_name = pkg.get("License", "")
                        if any(r in license_name for r in restricted):
                            issues.append({
                                "package": pkg.get("Name"),
                                "license": license_name,
                                "issue": "Restrictive license"
                            })

                    return json.dumps({
                        "language": "python",
                        "tool": "pip-licenses",
                        "total_packages": len(licenses),
                        "licenses": licenses,
                        "compliance_issues": issues,
                        "issue_count": len(issues)
                    })
                except Exception:
                    pass

        # JavaScript: Use license-checker
        if (ROOT / "package.json").exists():
            cmd = "npx license-checker --json"
            proc = _run_shell(cmd, timeout=60)

            try:
                licenses = json.loads(proc.stdout) if proc.stdout else {}

                restricted = ["GPL-3.0", "AGPL-3.0", "GPL-2.0"]
                issues: List[Dict[str, Any]] = []

                for pkg_name, pkg_info in licenses.items():
                    license_name = pkg_info.get("licenses", "")
                    if any(r in str(license_name) for r in restricted):
                        issues.append({
                            "package": pkg_name,
                            "license": license_name,
                            "issue": "Restrictive license"
                        })

                return json.dumps({
                    "language": "javascript",
                    "tool": "license-checker",
                    "total_packages": len(licenses),
                    "compliance_issues": issues,
                    "issue_count": len(issues)
                })
            except Exception:
                pass

        return json.dumps({
            "message": "No license checking tool available",
            "install": "pip install pip-licenses (Python) or npm install license-checker (JavaScript)"
        })

    except Exception as e:
        return json.dumps({"error": f"License check failed: {type(e).__name__}: {e}"})
