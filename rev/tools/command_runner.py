"""
Centralized safe subprocess execution module.

This module provides secure command execution with:
- Command injection prevention (no shell=True)
- Command allowlisting
- Shell metacharacter blocking
- Interrupt support for cancellation
- Timeout protection
- Output streaming to prevent memory issues

Security Design:
- All commands are parsed via shlex.split() and executed with shell=False
- Shell metacharacters (&&, ;, |, >, <, backticks, $(), etc.) are hard-rejected
- Only allowlisted command names can be executed
- Arguments are validated to prevent token injection

Interrupt Design:
- Commands can be interrupted via get_escape_interrupt() flag
- Processes are terminated gracefully, then killed if needed
- Streaming output is supported with interrupt checking
"""

import os
import re
import shlex
import subprocess
import time
import json
import pathlib
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from rev import config
from rev.config import ensure_escape_is_cleared, get_escape_interrupt


# Security: Forbidden patterns that indicate shell injection attempts
FORBIDDEN_RE = re.compile(r"[;&|><`]|(\$\()|\r|\n")

# Security: Forbidden tokens that should never appear in command arguments
FORBIDDEN_TOKENS = {"&&", "||", ";", "|", "&", ">", "<", ">>", "2>", "1>", "<<",
                    "2>&1", "1>&2", "`", "$(", "${"}

# Security: Allowlist of permitted commands
# This should be expanded based on actual requirements
ALLOW_CMDS = {
    # Git commands
    "git",
    # Python commands
    "python", "python3", "py", "pytest", "pip", "pip3",
    # Node.js commands
    "node", "npm", "npx", "yarn", "pnpm",
    # Build tools
    "make", "cmake", "cargo", "go",
    # Linters and formatters
    "ruff", "mypy", "pylint", "black", "isort", "flake8",
    "eslint", "prettier",
    # Test runners
    "jest", "vitest", "mocha",
    # Other tools
    "docker", "docker-compose",
    "grep", "find", "ls", "cat", "echo", "pwd",
}

# Add any custom allowed commands from config
if hasattr(config, 'ALLOW_CMDS'):
    ALLOW_CMDS.update(config.ALLOW_CMDS)


def _parse_and_validate(cmd: str) -> Tuple[bool, str, List[str]]:
    """Parse and validate a command string for safe execution.

    Args:
        cmd: Command string to parse and validate

    Returns:
        Tuple of (is_valid, error_message, parsed_args)
        - is_valid: True if command is safe to execute
        - error_message: Error description if not valid, empty string otherwise
        - parsed_args: List of command arguments if valid, empty list otherwise

    Security checks:
    1. Reject shell metacharacters in the raw command string
    2. Parse with shlex.split() to get individual tokens
    3. Check that command name is in allowlist
    4. Check that no forbidden tokens appear in arguments
    """
    # Check 1: Raw string validation for shell metacharacters
    if FORBIDDEN_RE.search(cmd):
        return False, "shell metacharacters not allowed (&&, ;, |, >, <, `, $(), etc.)", []

    # Check 2: Parse command into tokens
    try:
        args = shlex.split(cmd, posix=(os.name != "nt"))
    except ValueError as e:
        return False, f"failed to parse command: {e}", []

    if not args:
        return False, "empty command", []

    # Check 3: Validate command name is in allowlist
    cmd_name = args[0]

    # Special case: Allow full paths to Python executable
    if "python" in cmd_name.lower():
        # Extract just the executable name
        cmd_base = pathlib.Path(cmd_name).name.lower()
        if cmd_base not in {"python.exe", "python3.exe", "python", "python3", "py.exe", "py"}:
            return False, f"command not allowed: {cmd_name}", []
    elif cmd_name not in ALLOW_CMDS:
        return False, f"command not allowed: {cmd_name}", []

    # Check 4: Validate no forbidden tokens in arguments
    if any(tok in FORBIDDEN_TOKENS for tok in args):
        return False, "shell operators not allowed in arguments", []

    return True, "", args


def run_command_safe(
    cmd: str,
    *,
    timeout: int = 300,
    cwd: Optional[Path] = None,
    capture_output: bool = True,
    check_interrupt: bool = False,
) -> Dict[str, Any]:
    """Execute a command safely with security validation.

    Args:
        cmd: Command string to execute
        timeout: Maximum execution time in seconds
        cwd: Working directory (defaults to config.ROOT)
        capture_output: Whether to capture stdout/stderr
        check_interrupt: Whether to check for interrupt flag during execution

    Returns:
        Dict with execution results:
        - rc: Return code
        - stdout: Standard output (if captured)
        - stderr: Standard error (if captured)
        - blocked: True if command was blocked for security reasons
        - error: Error message if blocked or failed
        - cmd: Original command string
        - interrupted: True if interrupted by user

    Security:
        All commands are validated before execution. Shell metacharacters
        and non-allowlisted commands are rejected.
    """
    if cwd is None:
        cwd = config.ROOT

    # Validate command before execution
    is_valid, error_msg, args = _parse_and_validate(cmd)

    if not is_valid:
        return {
            "blocked": True,
            "error": error_msg,
            "cmd": cmd,
            "rc": -1,
        }

    # Execute safely with shell=False
    try:
        proc = subprocess.Popen(
            args,
            shell=False,  # CRITICAL: Never use shell=True
            cwd=str(cwd),
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Support interrupt checking for long-running commands
        if check_interrupt:
            stdout_data, stderr_data = _communicate_with_interrupt(proc, timeout)
            interrupted = get_escape_interrupt()
        else:
            try:
                stdout_data, stderr_data = proc.communicate(timeout=timeout)
                interrupted = False
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_data, stderr_data = proc.communicate()
                return {
                    "timeout": timeout,
                    "cmd": cmd,
                    "rc": -1,
                    "error": f"command exceeded {timeout}s timeout",
                }

        return {
            "rc": proc.returncode,
            "stdout": stdout_data or "",
            "stderr": stderr_data or "",
            "cmd": cmd,
            "interrupted": interrupted,
        }

    except FileNotFoundError:
        return {
            "error": f"command not found: {args[0]}",
            "cmd": cmd,
            "rc": -1,
        }
    except OSError as e:
        return {
            "error": f"OS error: {e}",
            "cmd": cmd,
            "rc": -1,
        }


def _communicate_with_interrupt(
    proc: subprocess.Popen,
    timeout: int,
) -> Tuple[str, str]:
    """Communicate with process while checking for interrupt flag.

    Args:
        proc: Running subprocess
        timeout: Maximum time to wait

    Returns:
        Tuple of (stdout, stderr) as strings

    This function polls the process and checks the interrupt flag.
    If interrupted, it terminates the process gracefully, then kills if needed.
    """
    start_time = time.time()
    poll_interval = 0.1  # Check every 100ms

    while True:
        # Check if process has finished
        if proc.poll() is not None:
            # Process finished, get remaining output
            stdout, stderr = proc.communicate()
            return stdout or "", stderr or ""

        # Check for interrupt flag
        if get_escape_interrupt():
            # User requested cancellation
            try:
                proc.terminate()
                # Wait briefly for graceful termination
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Process didn't terminate, force kill
                    proc.kill()
                    proc.wait()
            except Exception:
                pass

            stdout, stderr = proc.communicate()
            return stdout or "", stderr or ""

        # Check for timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            proc.kill()
            stdout, stderr = proc.communicate()
            return stdout or "", stderr or ""

        # Sleep briefly before next check
        time.sleep(poll_interval)


def run_command_streamed(
    cmd: str,
    *,
    timeout: int = 300,
    cwd: Optional[Path] = None,
    stdout_limit: int = 8000,
    stderr_limit: int = 8000,
    check_interrupt: bool = True,
) -> Dict[str, Any]:
    """Execute a command with output streaming to prevent memory issues.

    This is useful for commands that produce large amounts of output.
    Output is written to temporary files, then the last N lines are returned.

    Args:
        cmd: Command string to execute
        timeout: Maximum execution time in seconds
        cwd: Working directory (defaults to config.ROOT)
        stdout_limit: Maximum characters to return from stdout
        stderr_limit: Maximum characters to return from stderr
        check_interrupt: Whether to check for interrupt flag

    Returns:
        Dict with execution results (same as run_command_safe)
    """
    if cwd is None:
        cwd = config.ROOT

    # Validate command before execution
    is_valid, error_msg, args = _parse_and_validate(cmd)

    if not is_valid:
        return {
            "blocked": True,
            "error": error_msg,
            "cmd": cmd,
            "rc": -1,
        }

    # Create temporary files for output streaming
    import tempfile
    stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', errors='replace')
    stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', errors='replace')

    try:
        proc = subprocess.Popen(
            args,
            shell=False,  # CRITICAL: Never use shell=True
            cwd=str(cwd),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # Wait for completion with interrupt support
        if check_interrupt:
            start_time = time.time()
            poll_interval = 0.1

            while True:
                if proc.poll() is not None:
                    break

                if get_escape_interrupt():
                    try:
                        proc.terminate()
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                    except Exception:
                        pass
                    break

                elapsed = time.time() - start_time
                if elapsed > timeout:
                    proc.kill()
                    proc.wait()
                    break

                time.sleep(poll_interval)
        else:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        # Close file handles and read output
        stdout_file.close()
        stderr_file.close()

        # Read last N characters from output files
        with open(stdout_file.name, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size > stdout_limit:
                f.seek(size - stdout_limit)
            stdout_data = f.read()

        with open(stderr_file.name, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size > stderr_limit:
                f.seek(size - stderr_limit)
            stderr_data = f.read()

        return {
            "rc": proc.returncode,
            "stdout": stdout_data,
            "stderr": stderr_data,
            "cmd": cmd,
            "interrupted": get_escape_interrupt(),
        }

    finally:
        # Clean up temporary files
        try:
            os.unlink(stdout_file.name)
            os.unlink(stderr_file.name)
        except Exception:
            pass


# Backwards compatibility: Provide run_cmd and run_tests interfaces
def run_cmd(cmd: str, timeout: int = 300) -> str:
    """Run a shell command (backwards compatible interface).

    Returns:
        JSON string with execution results
    """
    result = run_command_streamed(
        cmd,
        timeout=timeout,
        stdout_limit=8000,
        stderr_limit=8000,
        check_interrupt=True,
    )
    return json.dumps(result)


def run_tests(cmd: str = "pytest -q", timeout: int = 600) -> str:
    """Run test suite (backwards compatible interface).

    Returns:
        JSON string with execution results
    """
    result = run_command_streamed(
        cmd,
        timeout=timeout,
        stdout_limit=12000,
        stderr_limit=4000,
        check_interrupt=True,
    )
    return json.dumps(result)
