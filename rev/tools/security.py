#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security scanning and analysis utilities."""

import json
import shlex
from typing import Dict, Any, List

from rev.config import ROOT
from rev.tools.utils import _run_shell, _safe_path


def scan_code_security(path: str = ".", tool: str = "auto") -> str:
    """Perform static security analysis on code.

    Args:
        path: Path to scan (file or directory)
        tool: Security tool to use (bandit, semgrep, auto)

    Returns:
        JSON string with security findings
    """
    try:
        scan_path = _safe_path(path)
        if not scan_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        findings: List[Dict[str, Any]] = []
        tools_used: List[str] = []

        # Python: Use bandit
        if tool in ["auto", "bandit"]:
            cmd = f"bandit -r {shlex.quote(str(scan_path))} -f json"
            proc = _run_shell(cmd, timeout=120)

            if proc.returncode != 127:  # Command exists
                try:
                    bandit_data = json.loads(proc.stdout) if proc.stdout else {}
                    results = bandit_data.get("results", [])
                    findings.extend(results)
                    tools_used.append("bandit")
                except Exception:
                    pass

        # Multi-language: Use semgrep
        if tool in ["auto", "semgrep"]:
            cmd = f"semgrep --config=auto --json {shlex.quote(str(scan_path))}"
            proc = _run_shell(cmd, timeout=120)

            if proc.returncode != 127:
                try:
                    semgrep_data = json.loads(proc.stdout) if proc.stdout else {}
                    results = semgrep_data.get("results", [])
                    findings.extend(results)
                    tools_used.append("semgrep")
                except Exception:
                    pass

        if not tools_used:
            return json.dumps({
                "error": "No security scanning tools available",
                "message": "Install bandit (Python) or semgrep: pip install bandit semgrep"
            })

        # Categorize by severity
        by_severity: Dict[str, List[Dict[str, Any]]] = {}
        for finding in findings:
            severity = finding.get("severity", "MEDIUM").upper()
            if severity not in by_severity:
                by_severity[severity] = []
            by_severity[severity].append(finding)

        return json.dumps({
            "scanned": str(scan_path.relative_to(ROOT)),
            "tools": tools_used,
            "findings": findings,
            "count": len(findings),
            "by_severity": {k: len(v) for k, v in by_severity.items()}
        })

    except Exception as e:
        return json.dumps({"error": f"Security scan failed: {type(e).__name__}: {e}"})


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
