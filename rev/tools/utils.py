#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utility functions for rev tools."""

import json
import os
import re
import sys
import pathlib
import subprocess
import shlex
import platform
from typing import Dict, Any

try:
    import requests
except ImportError:
    requests = None

try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    paramiko = None

# Import configuration from rev.config
from rev.config import ROOT, EXCLUDE_DIRS, MAX_FILE_BYTES


def _safe_path(rel: str) -> pathlib.Path:
    """Resolve path safely within repo root.

    Args:
        rel: Relative path from root

    Returns:
        Resolved pathlib.Path object

    Raises:
        ValueError: If path escapes root directory
    """
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT)):
        raise ValueError(f"Path escapes repo: {rel}")
    return p


def _run_shell(cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute shell command in repository root.

    Args:
        cmd: Shell command to execute
        timeout: Command timeout in seconds (default: 300)

    Returns:
        CompletedProcess with returncode, stdout, stderr
    """
    return subprocess.run(
        cmd,
        shell=True,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def install_package(package: str) -> str:
    """Install a Python package.

    Args:
        package: Package name or spec to install

    Returns:
        JSON string with installation result
    """
    try:
        result = _run_shell(f"pip install {shlex.quote(package)}", timeout=300)
        return json.dumps({
            "installed": package,
            "returncode": result.returncode,
            "output": result.stdout + result.stderr
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def web_fetch(url: str) -> str:
    """Fetch content from a URL.

    Args:
        url: URL to fetch

    Returns:
        JSON string with response data or error
    """
    if not requests:
        return json.dumps({"error": "requests library not available. Install with: pip install requests"})

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return json.dumps({
            "url": url,
            "status_code": response.status_code,
            "content": response.text[:50000],  # Limit to 50KB
            "headers": dict(response.headers)
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def execute_python(code: str) -> str:
    """Execute Python code in a restricted context.

    SECURITY WARNING: This function provides limited sandboxing and should only be used
    with trusted code. The restricted namespace limits but does not eliminate security risks.

    Args:
        code: Python code to execute

    Returns:
        JSON string with execution result
    """
    try:
        import io
        import contextlib

        # Create a restricted namespace (limited builtins, safe modules only)
        # WARNING: This is NOT a complete sandbox - use with caution
        safe_builtins = {
            'abs': abs, 'all': all, 'any': any, 'bin': bin, 'bool': bool,
            'chr': chr, 'dict': dict, 'enumerate': enumerate, 'filter': filter,
            'float': float, 'format': format, 'hex': hex, 'int': int,
            'isinstance': isinstance, 'len': len, 'list': list, 'map': map,
            'max': max, 'min': min, 'oct': oct, 'ord': ord, 'pow': pow,
            'print': print, 'range': range, 'reversed': reversed, 'round': round,
            'set': set, 'sorted': sorted, 'str': str, 'sum': sum, 'tuple': tuple,
            'type': type, 'zip': zip,
            # Allow limited exceptions
            'Exception': Exception, 'ValueError': ValueError, 'TypeError': TypeError,
        }

        namespace = {
            '__builtins__': safe_builtins,
            'json': json,
            're': re,
            # DO NOT include 'os' or 'pathlib' - filesystem access removed
        }

        # Capture output
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exec(code, namespace)

        return json.dumps({
            "executed": True,
            "output": output.getvalue()
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def get_system_info() -> str:
    """Get system information (OS, version, architecture, shell type).

    Returns:
        JSON string with system information
    """
    try:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "is_windows": platform.system() == "Windows",
            "is_linux": platform.system() == "Linux",
            "is_macos": platform.system() == "Darwin",
            "shell_type": "powershell" if platform.system() == "Windows" else "bash"
        }
        return json.dumps(info)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
