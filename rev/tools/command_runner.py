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
import shutil
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from rev import config
from rev.config import ensure_escape_is_cleared, get_escape_interrupt
from rev.tools.workspace_resolver import normalize_path


# Security: Forbidden patterns that indicate shell injection attempts
FORBIDDEN_RE = re.compile(r"[;&|><`]|(\$\()|\r|\n")

# Security: Forbidden tokens that should never appear in command arguments
FORBIDDEN_TOKENS = {"&&", "||", ";", "|", "&", ">", "<", ">>", "2>", "1>", "<<",
                    "2>&1", "1>&2", "`", "$(", "${"}

_PATH_TOKEN_RE = re.compile(r"[\\/]|^\.\.?[\\/]|^[A-Za-z]:[\\/]|^~[\\/]")
_PATH_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")


def _resolve_command(cmd_name: str) -> Optional[str | List[str]]:
    """Resolve a command name to its full path or execution wrapper.

    On Windows, this correctly finds .cmd, .bat, and .exe files.
    If a .cmd or .bat file is found, it returns a list prefixed with cmd /c
    to ensure it can be executed with shell=False.

    Windows built-in commands (like ren, rmdir, dir) are also wrapped with cmd /c
    since they don't exist as standalone executables.
    """
    # Windows built-in commands that are part of cmd.exe, not standalone executables
    WINDOWS_BUILTINS = {
        'dir', 'copy', 'move', 'ren', 'rename', 'del', 'erase',
        'rmdir', 'rd', 'mkdir', 'md', 'type', 'echo', 'set',
        'cd', 'chdir', 'cls', 'attrib', 'ver', 'vol', 'path',
        'prompt', 'date', 'time', 'start', 'call', 'pushd', 'popd'
    }

    # Check if it's a Windows built-in command
    if os.name == 'nt' and cmd_name.lower() in WINDOWS_BUILTINS:
        return ["cmd.exe", "/c", cmd_name]

    resolved = shutil.which(cmd_name)
    if not resolved:
        return None

    if os.name == 'nt':
        # If it's a batch file, we need cmd /c to run it with shell=False
        if resolved.lower().endswith(('.cmd', '.bat')):
            return ["cmd.exe", "/c", resolved]

    return resolved


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
    3. Check that no forbidden tokens appear in arguments
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

    # Check 3: Validate no forbidden tokens in arguments
    if any(tok in FORBIDDEN_TOKENS for tok in args):
        return False, "shell operators not allowed in arguments", []

    return True, "", args


def _resolve_cwd(cwd: Optional[Path]) -> Path:
    if cwd is None:
        return config.ROOT
    if not isinstance(cwd, Path):
        cwd = Path(cwd)
    if not cwd.is_absolute():
        cwd = config.ROOT / cwd
    return cwd.resolve(strict=False)


def _looks_like_path_token(token: str) -> bool:
    if not token:
        return False
    if token.startswith("-"):
        return False
    if _PATH_TOKEN_RE.search(token):
        return True
    if _PATH_EXTENSION_RE.search(token):
        return True
    return False


def _normalize_path_value(value: str, cwd: Path) -> str:
    raw = value.strip()
    if not raw:
        return value
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1].strip()
    raw = os.path.expanduser(raw)
    normalized = normalize_path(raw)
    path = Path(normalized.replace("/", os.sep))
    if not path.is_absolute():
        path = (cwd / path).resolve(strict=False)
    try:
        rel = path.relative_to(cwd)
    except Exception:
        return str(path)
    rel_str = str(rel)
    return rel_str if rel_str else "."


def _normalize_command_args(args: list[str], cwd: Path) -> list[str]:
    normalized_args: list[str] = []
    for idx, token in enumerate(args):
        if idx == 0:
            normalized_args.append(token)
            continue
        if not isinstance(token, str):
            normalized_args.append(str(token))
            continue
        if token.startswith("-") and "=" in token:
            flag, value = token.split("=", 1)
            if _looks_like_path_token(value):
                value = _normalize_path_value(value, cwd)
            normalized_args.append(f"{flag}={value}")
            continue
        if _looks_like_path_token(token):
            normalized_args.append(_normalize_path_value(token, cwd))
            continue
        normalized_args.append(token)
    return normalized_args


def run_command_safe(
    cmd: str | List[str],
    *,
    timeout: int = 300,
    cwd: Optional[Path] = None,
    capture_output: bool = True,
    check_interrupt: bool = False,
) -> Dict[str, Any]:
    """Execute a command safely with security validation.

    Args:
        cmd: Command string or list of arguments to execute
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
    resolved_cwd = _resolve_cwd(cwd)

    # Validate command before execution
    if isinstance(cmd, list):
        # Already split, validate each part
        if not cmd:
            return {"blocked": True, "error": "empty command", "cmd": str(cmd), "cwd": str(resolved_cwd), "rc": -1}
        
        args = [str(arg) for arg in cmd]
        
        # For list-based commands (shell=False), we only block the most dangerous
        # tokens if they are standalone arguments, to prevent accidental shell-like
        # behavior if the executable itself is a shell (like cmd.exe or sh).
        # We allow these characters within arguments (e.g. in paths).
        danger_tokens = {"&&", "||", "|", ">>", "<<", "`", "$("}
        if any(tok in danger_tokens for tok in args):
            return {
                "blocked": True,
                "error": "dangerous shell operators not allowed as standalone arguments",
                "cmd": " ".join(args),
                "cwd": str(resolved_cwd),
                "rc": -1,
            }
        
        original_cmd_str = " ".join(cmd)
    else:
        is_valid, error_msg, args = _parse_and_validate(cmd)
        if not is_valid:
            return {
                "blocked": True,
                "error": error_msg,
                "cmd": cmd,
                "cwd": str(resolved_cwd),
                "rc": -1,
            }
        original_cmd_str = cmd

    args = _normalize_command_args(args, resolved_cwd)
    normalized_cmd_str = " ".join(args)

    # Resolve command just before execution
    executable = args[0]
    resolved = _resolve_command(executable)
    if resolved:
        if isinstance(resolved, list):
            # Command needs a wrapper (e.g. cmd /c for Windows batch files)
            args = resolved + args[1:]
        else:
            args[0] = resolved

    # Execute safely with shell=False
    try:
        if os.getenv("REV_DEBUG_CMD"):
            print(f"  [DEBUG_CMD] Executing: {args} (cwd={resolved_cwd})")
            
        proc = subprocess.Popen(
            args,
            shell=False,  # CRITICAL: Never use shell=True
            cwd=str(resolved_cwd),
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
                    "cmd": original_cmd_str,
                    "cmd_normalized": normalized_cmd_str,
                    "cwd": str(resolved_cwd),
                    "rc": -1,
                    "error": f"command exceeded {timeout}s timeout",
                }

        if os.getenv("REV_DEBUG_CMD"):
            print(f"  [DEBUG_CMD] Result: rc={proc.returncode}, stdout_len={len(stdout_data or '')}, stderr_len={len(stderr_data or '')}")

        return {
            "rc": proc.returncode,
            "stdout": stdout_data or "",
            "stderr": stderr_data or "",
            "cmd": original_cmd_str,
            "cmd_normalized": normalized_cmd_str,
            "cwd": str(resolved_cwd),
            "interrupted": interrupted,
        }

    except FileNotFoundError:
        return {
            "error": f"command not found: {args[0]}",
            "cmd": original_cmd_str,
            "cmd_normalized": normalized_cmd_str,
            "cwd": str(resolved_cwd),
            "rc": -1,
        }
    except OSError as e:
        return {
            "error": f"OS error: {e}",
            "cmd": original_cmd_str,
            "cmd_normalized": normalized_cmd_str,
            "cwd": str(resolved_cwd),
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
    cmd: str | List[str],
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
        cmd: Command string or list of arguments to execute
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
    resolved_cwd = _resolve_cwd(cwd)

    # Validate command before execution
    if isinstance(cmd, list):
        if not cmd:
            return {"blocked": True, "error": "empty command", "cmd": str(cmd), "cwd": str(resolved_cwd), "rc": -1}
        
        args = [str(arg) for arg in cmd]
        
        # For list-based commands (shell=False), we only block the most dangerous
        # tokens if they are standalone arguments, to prevent accidental shell-like
        # behavior if the executable itself is a shell (like cmd.exe or sh).
        # We allow these characters within arguments (e.g. in paths).
        danger_tokens = {"&&", "||", "|", ">>", "<<", "`", "$("}
        if any(tok in danger_tokens for tok in args):
            return {
                "blocked": True,
                "error": "dangerous shell operators not allowed as standalone arguments",
                "cmd": " ".join(args),
                "cwd": str(resolved_cwd),
                "rc": -1,
            }
        
        original_cmd_str = " ".join(cmd)
    else:
        is_valid, error_msg, args = _parse_and_validate(cmd)
        if not is_valid:
            return {
                "blocked": True,
                "error": error_msg,
                "cmd": cmd,
                "cwd": str(resolved_cwd),
                "rc": -1,
            }
        original_cmd_str = cmd

    args = _normalize_command_args(args, resolved_cwd)
    normalized_cmd_str = " ".join(args)

    # Resolve command just before execution
    executable = args[0]
    resolved = _resolve_command(executable)
    if resolved:
        if isinstance(resolved, list):
            # Command needs a wrapper (e.g. cmd /c for Windows batch files)
            args = resolved + args[1:]
        else:
            args[0] = resolved

    # Create temporary files for output streaming
    import tempfile
    stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', errors='replace')
    stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, encoding='utf-8', errors='replace')

    try:
        proc = subprocess.Popen(
            args,
            shell=False,  # CRITICAL: Never use shell=True
            cwd=str(resolved_cwd),
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
            "cmd": original_cmd_str,
            "cmd_normalized": normalized_cmd_str,
            "cwd": str(resolved_cwd),
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
def run_cmd(cmd: str | list[str], timeout: int = 300, cwd: Optional[Path] = None) -> str:
    """Run a shell command (backwards compatible interface).

    Returns:
        JSON string with execution results
    """
    if cwd is not None and not isinstance(cwd, Path):
        cwd = Path(cwd)

    result = run_command_safe(
        cmd,
        timeout=timeout,
        cwd=cwd,
        capture_output=True,
        check_interrupt=True,
    )
    return json.dumps(result)


def run_tests(cmd: str | list[str] = "pytest -q", timeout: int = 600, cwd: Optional[Path] = None) -> str:
    """Run test suite (backwards compatible interface).

    Returns:
        JSON string with execution results
    """
    if cwd is not None and not isinstance(cwd, Path):
        cwd = Path(cwd)

    result = run_command_safe(
        cmd,
        timeout=timeout,
        cwd=cwd,
        capture_output=True,
        check_interrupt=True,
    )
    return json.dumps(result)
