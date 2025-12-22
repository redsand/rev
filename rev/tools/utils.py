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
from rev.config import EXCLUDE_DIRS, MAX_FILE_BYTES
from rev.tools.workspace_resolver import resolve_workspace_path
from rev.workspace import get_workspace


def _safe_path(rel: str) -> pathlib.Path:
    """Resolve path safely within repo root.

    Args:
        rel: Relative path from root

    Returns:
        Resolved pathlib.Path object

    Raises:
        ValueError: If path escapes root directory
    """
    resolved = resolve_workspace_path(rel, purpose="tool operation")
    return resolved.abs_path


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
        cwd=str(get_workspace().root),
        text=True,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


def quote_cmd_arg(arg: str) -> str:
    """Quote a command line argument for the current platform's default shell.

    On POSIX systems, this uses shlex.quote. On Windows (where shell=True uses cmd.exe),
    this uses subprocess.list2cmdline which provides compatible quoting for cmd.exe.
    """
    if os.name == 'nt':
        return subprocess.list2cmdline([str(arg)])
    return shlex.quote(str(arg))


def install_package(package: str) -> str:
    """Install a Python package.

    Args:
        package: Package name or spec to install

    Returns:
        JSON string with installation result
    """
    try:
        result = _run_shell(f"pip install {quote_cmd_arg(package)}", timeout=300)
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


def run_python_diagnostic(script: str, description: str = "") -> str:
    """Run a Python script for runtime diagnostics in the workspace context.

    Unlike execute_python (which runs in a restricted sandbox), this runs Python
    code in the actual workspace directory with full import capabilities. This is
    essential for diagnosing module import issues, testing auto-registration logic,
    and inspecting actual Python runtime behavior.

    SECURITY: Only use with trusted diagnostic code. This runs with full Python access.

    Args:
        script: Python code to execute (can include imports from workspace)
        description: Optional description of what this diagnostic tests

    Returns:
        JSON string with stdout, stderr, and exit code

    Example:
        script = '''
import lib.analysts as am
from lib.analysts import BreakoutAnalyst
print(f"Module: {am.__name__}")
print(f"Class module: {BreakoutAnalyst.__module__}")
        '''
        result = run_python_diagnostic(script, "Test module names")
    """
    import subprocess
    import tempfile
    from pathlib import Path
    from rev import config

    try:
        # Create a temporary Python script file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script)
            script_path = f.name

        try:
            # Run the script from the workspace directory
            result = subprocess.run(
                ['python', script_path],
                cwd=str(config.ROOT),
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout for diagnostic scripts
            )

            return json.dumps({
                "description": description,
                "rc": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0,
            })
        finally:
            # Clean up temp file
            try:
                Path(script_path).unlink()
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        return json.dumps({
            "description": description,
            "error": "Diagnostic script timed out after 30 seconds",
            "timeout": True,
        })
    except Exception as e:
        return json.dumps({
            "description": description,
            "error": f"{type(e).__name__}: {e}",
        })


def inspect_module_hierarchy(module_path: str) -> str:
    """Inspect a Python module's hierarchy and class/function module names.

    This diagnostic tool helps debug import and auto-registration issues by
    revealing the actual module names of classes after import. Essential for
    diagnosing issues where module.__name__ doesn't match class.__module__
    (e.g., when a file becomes a package).

    Args:
        module_path: Python import path (e.g., "lib.analysts")

    Returns:
        JSON string with module hierarchy info

    Example:
        result = inspect_module_hierarchy("lib.analysts")
        # Shows: module.__name__, all classes and their __module__ attributes
    """
    script = f'''
import sys
import inspect
import json

try:
    # Import the module
    module = __import__("{module_path}", fromlist=[""])

    result = {{
        "module_path": "{module_path}",
        "module_name": module.__name__,
        "module_file": getattr(module, "__file__", None),
        "is_package": hasattr(module, "__path__"),
        "classes": {{}},
        "functions": {{}},
    }}

    # Inspect all classes
    for name, obj in inspect.getmembers(module, inspect.isclass):
        result["classes"][name] = {{
            "module": obj.__module__,
            "matches_parent": obj.__module__ == module.__name__,
            "starts_with_parent": obj.__module__.startswith(module.__name__),
        }}

    # Inspect all functions
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        result["functions"][name] = {{
            "module": obj.__module__,
        }}

    print(json.dumps(result, indent=2))

except ImportError as e:
    print(json.dumps({{"error": f"ImportError: {{e}}"}}, indent=2))
except Exception as e:
    print(json.dumps({{"error": f"{{type(e).__name__}}: {{e}}"}}, indent=2))
'''

    return run_python_diagnostic(script, f"Inspect module hierarchy: {module_path}")


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
