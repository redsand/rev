#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Git operations tools for rev."""

import json
import os
import pathlib
import re
import shlex
import subprocess
import tempfile
from typing import Optional, Iterable

# Patches larger than this many characters often hit context limits in agent prompts
# or produce opaque failures. When we detect a patch above this size that still
# fails validation, we return a hint encouraging the caller to split the change
# into smaller chunks.
_LARGE_PATCH_HINT_THRESHOLD = 120_000

from rev import config
from rev.debug_logger import prune_old_logs
from rev.tools.utils import quote_cmd_arg

# Backward compatibility for tests
ROOT = config.ROOT


# ========== Helper Function ==========

def _run_shell(cmd: str | list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute shell command (DEPRECATED - use command_runner module instead).

    This function is maintained for backward compatibility only.
    New code should use rev.tools.command_runner.run_command_safe()
    """
    from rev.tools.command_runner import run_command_safe

    try:
        result = run_command_safe(cmd, timeout=timeout, check_interrupt=False)

        # Return a CompletedProcess object for compatibility
        if result.get("blocked"):
            # Command was blocked for security reasons
            return subprocess.CompletedProcess(
                args=str(cmd),
                returncode=-1,
                stdout="",
                stderr=f"BLOCKED: {result.get('error', 'security violation')}"
            )

        return subprocess.CompletedProcess(
            args=str(cmd),
            returncode=result.get("rc", -1),
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", "")
        )
    except OSError as exc:
        # On Windows low-memory/paging-file failures (e.g., WinError 1455), return a CompletedProcess-like
        # object so callers can surface a clear message instead of crashing.
        return subprocess.CompletedProcess(
            args=str(cmd),
            returncode=1,
            stdout="",
            stderr=str(exc),
        )


def _create_log_file(prefix: str) -> pathlib.Path:
    """Create a log file inside .rev/logs for streaming command output."""

    log_dir = config.LOGS_DIR
    log_dir.mkdir(exist_ok=True, parents=True)

    fd, path_str = tempfile.mkstemp(prefix=prefix, suffix=".log", dir=log_dir)
    os.close(fd)
    prune_old_logs(log_dir, config.LOG_RETENTION_LIMIT)
    return pathlib.Path(path_str)


def _tail_file(path: pathlib.Path, limit: int) -> str:
    """Read the last ``limit`` characters from ``path`` without loading the file."""

    if limit <= 0 or not path.exists():
        return ""

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size > limit:
            handle.seek(size - limit)
        else:
            handle.seek(0)
        return handle.read()


def _working_tree_snapshot() -> str:


    """Return a lightweight snapshot of working tree changes.





    We use ``git status --porcelain`` so we can detect when an apply operation


    reports success but does not actually modify the tree (for example, when an


    empty or already-applied patch slips through).


    """


    if not is_git_repo():


        return ""





    proc = _run_shell("git status --porcelain")


    return proc.stdout


def _extract_patch_paths(lines: list[str]) -> set[str]:
    """Return the set of file paths referenced by a patch."""

    paths: set[str] = set()
    for line in lines:
        if not line.startswith(("+++ ", "--- ")):
            continue

        try:
            _, raw_path = line.split(" ", 1)
        except ValueError:
            continue

        raw_path = raw_path.strip()
        if raw_path in {"/dev/null", "dev/null", "a/dev/null", "b/dev/null"}:
            continue

        if raw_path.startswith(("a/", "b/")):
            raw_path = raw_path[2:]

        paths.add(raw_path)

    return paths


def _split_patch_into_chunks(patch: str) -> list[str]:
    """Split a multi-file patch into file-scoped chunks.

    We attempt to keep ``diff --git`` and header lines attached to each file so
    downstream apply calls have the necessary context. Chunks without both
    ``---`` and ``+++`` headers are ignored to avoid sending malformed diffs to
    the apply routines.
    """

    # Prefer diff --git boundaries when available; otherwise fall back to the
    # first --- header for simple patches.
    if "diff --git" in patch:
        parts = re.split(r"(?m)^diff --git ", patch)
        # ``re.split`` drops the delimiter; put it back.
        chunks = [f"diff --git {p}" for p in parts if p.strip()]
    else:
        chunks = re.split(r"(?m)(?=^--- )", patch)
        chunks = [c for c in chunks if c.strip()]

    formatted: list[str] = []
    for chunk in chunks:
        if "--- " not in chunk or "+++ " not in chunk:
            continue
        formatted.append(chunk if chunk.endswith("\n") else f"{chunk}\n")

    return formatted


def _retry_plan_message(chunk_count: int) -> str:
    """Return guidance for retrying a failed patch application.

    The message encourages callers to keep engaging the LLM until it delivers a
    workable patch and to split the change into smaller, sequentially applied
    chunks when necessary.
    """

    target_chunks = max(2, chunk_count)
    return (
        "Patch failed to apply cleanly. Ask the model to retry until it returns "
        "a valid diff, and if failures persist, split the update into "
        f"~{target_chunks} smaller chunk(s) (for example, by file) and apply them "
        "one at a time."
    )


def _snapshot_paths(paths: set[str]) -> dict[str, Optional[bytes]]:
    """Capture the current content for a set of files.

    Missing files are represented by ``None`` so we can detect creations and
    deletions in addition to modifications.
    """

    snapshot: dict[str, Optional[bytes]] = {}
    for path in paths:
        full_path = config.ROOT / path
        snapshot[path] = full_path.read_bytes() if full_path.exists() else None
    return snapshot


def _normalize_patch_text(patch: str) -> str:
    """Normalize non-standard whitespace that can break patch parsing."""
    # Standardize newline handling first
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n")

    # Replace various Unicode whitespace characters with a standard space
    whitespace_pattern = re.compile(
        r'[\u00A0\u1680\u180E\u2000-\u200A\u202F\u205F\u3000]'
    )
    normalized = whitespace_pattern.sub(' ', normalized)

    # Remove zero-width characters
    zero_width_pattern = re.compile(r'[\u200B-\u200D\uFEFF]')
    normalized = zero_width_pattern.sub('', normalized)

    return normalized


def is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    # Check for .git directory or file (worktree) first to avoid running subprocess unnecessarily
    if (config.ROOT / ".git").exists():
        return True
        
    # Fallback to git command for nested repos or complex setups
    proc = _run_shell("git rev-parse --is-inside-work-tree")
    return proc.returncode == 0


# ========== Core Git Operations ==========

def git_diff(pathspec: str = ".", staged: bool = False, context: int = 3) -> str:
    """Get git diff for pathspec."""
    if not is_git_repo():
        return json.dumps({"rc": 1, "diff": "", "stderr": "Not a git repository"})

    args = ["git", "diff", f"-U{context}"]
    if staged:
        args.insert(1, "--staged")
    if pathspec:
        args.append(pathspec)
    proc = _run_shell(" ".join(quote_cmd_arg(a) for a in args))
    return json.dumps({"rc": proc.returncode, "diff": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})



def apply_patch(patch: str, dry_run: bool = False, *, _allow_chunking: bool = True) -> str:
    """Apply a unified diff patch with resilient validation.

    The previous implementation proved too brittle for the kinds of diffs that
    are produced in practice. This version mirrors common CLI workflows by
    validating with ``git apply --check`` first, falling back to a standard
    ``patch`` invocation, and only performing the apply step after validation
    succeeds. We also normalize problematic whitespace up front and provide
    clearer error reporting so callers can correct issues quickly.
    """

    normalized_patch = _normalize_patch_text(patch)
    if normalized_patch.lstrip().startswith("*** Begin Patch"):
        return json.dumps(
            {
                "success": False,
                "rc": 1,
                "stdout": "",
                "stderr": "",
                "dry_run": dry_run,
                "phase": "check",
                "error": (
                    "Unsupported patch format: received a Codex '*** Begin Patch' block. "
                    "Provide a unified diff (diff --git / ---/+++ with @@ hunks) for apply_patch."
                ),
            }
        )
    if not normalized_patch.endswith("\n"):
        normalized_patch = f"{normalized_patch}\n"

    patch_size = len(normalized_patch)
    chunked_parts = _split_patch_into_chunks(normalized_patch)
    large_patch_hint: Optional[str] = None
    if patch_size > _LARGE_PATCH_HINT_THRESHOLD:
        large_patch_hint = (
            "Patch is quite large; consider splitting it by file or feature "
            "so apply_patch can work reliably. For very large diffs you can also "
            "apply them locally with 'git apply --reject' and commit the result."
        )

    def _has_malformed_hunks(lines: list[str]) -> bool:
        """Detect obvious malformed hunk lines (missing +/-/space prefixes)."""

        in_hunk = False
        for line in lines:
            if line.startswith("@@"):
                in_hunk = True
                continue

            if in_hunk:
                if line.startswith("@@"):
                    continue
                if line.startswith("--- ") or line.startswith("+++ "):
                    in_hunk = False
                    continue
                if line.strip() and not line.startswith(("+", "-", " ", "\\")):
                    return True
        return False

    patch_lines = normalized_patch.splitlines()
    patch_paths = _extract_patch_paths(patch_lines)

    retry_plan = _retry_plan_message(len(chunked_parts))

    if _has_malformed_hunks(patch_lines):
        proc = subprocess.CompletedProcess("apply_patch", 1, "", "patch validation failed: unexpected hunk line")
        return json.dumps(
            {
                "success": False,
                "rc": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "dry_run": dry_run,
                "phase": "check",
                "error": "Patch failed basic validation",
            }
        )

    pre_status = _working_tree_snapshot()
    pre_contents = _snapshot_paths(patch_paths)

    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tf.write(normalized_patch)
        tf.flush()
        tfp = tf.name

    def _result(
        proc: subprocess.CompletedProcess,
        *,
        success: bool,
        already_applied: bool = False,
        phase: str,
        hint: Optional[str] = None,
        retry_plan: Optional[str] = None,
    ) -> str:
        result = {
            "success": success or already_applied,
            "rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "dry_run": dry_run,
            "phase": phase,
        }
        if already_applied:
            result["already_applied"] = True
        if not success and not already_applied:
            result["error"] = f"Patch failed to apply (exit code {proc.returncode})"
            if proc.stderr:
                result["error"] += f": {proc.stderr[:500]}"
            if hint:
                result["hint"] = hint
            if retry_plan:
                result["retry_plan"] = retry_plan
        return json.dumps(result)

    def _apply_patch_in_chunks(chunks: Iterable[str], dry_run: bool = False) -> Optional[str]:
        """Attempt to apply each file chunk independently."""
        if not chunks:
            return None

        for idx, chunk in enumerate(chunks, start=1):
            chunk_result = json.loads(apply_patch(chunk, dry_run=dry_run, _allow_chunking=False))
            if not chunk_result.get("success"):
                return json.dumps({
                    "success": False,
                    "rc": chunk_result.get("rc", 1),
                    "dry_run": dry_run,
                    "phase": "chunked",
                    "failed_chunk_index": idx,
                    "error": chunk_result.get("error", "Patch chunk failed to apply"),
                    "retry_plan": _retry_plan_message(len(chunked_parts)),
                })
        return json.dumps({"success": True, "phase": "chunked", "chunks_applied": len(chunked_parts)})

    try:
        strategies = [
            ("git", ["git", "apply", "--check", "--inaccurate-eof", "--whitespace=nowarn", tfp], False),
            ("git", ["git", "apply", "--check", "--inaccurate-eof", "--whitespace=nowarn", "--3way", tfp], True),
            ("patch", ["patch", "--batch", "--forward", "--dry-run", "-p1", "-i", tfp], False),
        ]
        
        if not is_git_repo():
            # Skip git strategies if not a repo to avoid 'fatal: not a git repository'
            strategies = [s for s in strategies if s[0] != "git"]

        check_proc: Optional[subprocess.CompletedProcess] = None
        use_three_way = False
        apply_mode: Optional[str] = None

        for runner, check_args, use_three_way_flag in strategies:
            check_proc = _run_shell(check_args)

            combined_output = (check_proc.stdout + check_proc.stderr).lower()
            if "patch already applied" in combined_output or "previously applied" in combined_output:
                return _result(check_proc, success=True, already_applied=True, phase="check")

            if check_proc.returncode == 0:
                use_three_way = use_three_way_flag
                apply_mode = runner
                break
        else:
            if is_git_repo():
                reverse_proc = _run_shell(["git", "apply", "--check", "--reverse", "--inaccurate-eof", tfp])
                reverse_output = (reverse_proc.stdout + reverse_proc.stderr).lower()
                if reverse_proc.returncode == 0 or "reversed" in reverse_output:
                    return _result(reverse_proc, success=True, already_applied=True, phase="check")
            else:
                # If not a git repo, we don't have a check_proc yet if we only had one strategy and it failed?
                # Actually, if is_git_repo is False, strategies list has only "patch".
                # If patch strategy failed, we are here.
                # check_proc would be the patch command's process.
                pass

            if _allow_chunking and not dry_run and len(chunked_parts) > 1:
                chunk_result = _apply_patch_in_chunks(chunked_parts, dry_run=dry_run)
                if chunk_result:
                    return chunk_result

            return _result(
                check_proc,
                success=False,
                phase="check",
                hint=large_patch_hint,
                retry_plan=retry_plan,
            )

        if dry_run:
            return _result(check_proc, success=True, phase="check")

        if apply_mode == "git":
            apply_args = ["git", "apply", "--inaccurate-eof", "--whitespace=nowarn"]
            if use_three_way:
                apply_args.append("--3way")
            apply_args.append(tfp)
            apply_proc = _run_shell(apply_args)
        else:
            apply_proc = _run_shell(["patch", "--batch", "--forward", "-p1", "-i", tfp])

        if apply_proc.returncode == 0:
            post_status = _working_tree_snapshot()
            post_contents = _snapshot_paths(patch_paths)

            if patch_paths:
                tree_changed = pre_contents != post_contents
            else:
                tree_changed = pre_status != post_status

            if not tree_changed:
                return json.dumps(
                    {
                        "success": False,
                        "rc": apply_proc.returncode,
                        "stdout": apply_proc.stdout,
                        "stderr": apply_proc.stderr,
                        "dry_run": dry_run,
                        "phase": "apply",
                        "error": (
                            "Patch command reported success, but no working tree changes were detected. "
                            "The patch may already be applied, empty, or truncated; please verify the diff contents "
                            "and file paths."
                        ),
                        "hint": large_patch_hint,
                        "retry_plan": retry_plan,
                    }
                )
            
            # Invalidate cache for all affected files
            from rev.cache import get_file_cache
            file_cache = get_file_cache()
            if file_cache is not None:
                for path_str in patch_paths:
                    file_cache.invalidate_file(config.ROOT / path_str)

        if apply_proc.returncode != 0 and _allow_chunking and not dry_run and len(chunked_parts) > 1:
            chunk_result = _apply_patch_in_chunks(chunked_parts, dry_run=dry_run)
            if chunk_result:
                return chunk_result

        return _result(
            apply_proc,
            success=apply_proc.returncode == 0,
            phase="apply",
            hint=large_patch_hint if apply_proc.returncode != 0 else None,
            retry_plan=retry_plan if apply_proc.returncode != 0 else None,
        )
    finally:
        try:
            os.unlink(tfp)
        except FileNotFoundError:
            pass
        except Exception as e:
            import sys
            print(f"Warning: Failed to clean up temporary patch file {tfp}: {e}", file=sys.stderr)


def git_add(files: str = ".") -> str:
    """Add files to git staging area."""
    if not is_git_repo():
        return json.dumps({"success": False, "error": "Not a git repository"})

    try:
        result = _run_shell(f"git add {quote_cmd_arg(files)}")
        success = result.returncode == 0
        if not success:
            return json.dumps({
                "success": False,
                "error": f"git add failed: {result.stderr}",
                "returncode": result.returncode
            })
        return json.dumps({
            "success": True,
            "added": True,
            "files": files,
            "output": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"})


def git_commit(message: str, add_files: bool = False, files: str = ".") -> str:
    """Commit changes to git.

    Args:
        message: Commit message
        add_files: Whether to add files before committing (default: False)
        files: Files to add if add_files is True (default: ".")
    """
    if not is_git_repo():
        return json.dumps({"success": False, "error": "Not a git repository"})

    try:
        # Optionally add files first
        if add_files:
            add_result = _run_shell(f"git add {quote_cmd_arg(files)}")
            if add_result.returncode != 0:
                return json.dumps({"success": False, "error": f"git add failed: {add_result.stderr}"})

        # Commit
        commit_result = _run_shell(f"git commit -m {quote_cmd_arg(message)}")
        if commit_result.returncode != 0:
            return json.dumps({"success": False, "error": f"git commit failed: {commit_result.stderr}"})

        return json.dumps({
            "success": True,
            "committed": True,
            "message": message,
            "output": commit_result.stdout
        })
    except Exception as e:
        return json.dumps({"success": False, "error": f"{type(e).__name__}: {e}"})


def git_status() -> str:
    """Get git status."""
    if not is_git_repo():
        return json.dumps({"status": "", "returncode": 1, "error": "Not a git repository"})

    try:
        result = _run_shell("git status")
        return json.dumps({
            "status": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_log(count: int = 10, oneline: bool = False) -> str:
    """Get git log."""
    if not is_git_repo():
        return json.dumps({"log": "", "returncode": 1, "error": "Not a git repository"})

    try:
        cmd = f"git log -n {int(count)}"
        if oneline:
            cmd += " --oneline"
        result = _run_shell(cmd)
        return json.dumps({
            "log": result.stdout,
            "returncode": result.returncode
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_branch(action: str = "list", branch_name: str = None) -> str:
    """Git branch operations (list, create, switch, current)."""
    if not is_git_repo():
        return json.dumps({"error": "Not a git repository"})

    try:
        if action == "list":
            result = _run_shell("git branch -a")
            return json.dumps({
                "action": "list",
                "branches": result.stdout,
                "returncode": result.returncode
            })
        elif action == "current":
            result = _run_shell("git branch --show-current")
            return json.dumps({
                "action": "current",
                "branch": result.stdout.strip(),
                "returncode": result.returncode
            })
        elif action == "create" and branch_name:
            result = _run_shell(f"git branch {quote_cmd_arg(branch_name)}")
            return json.dumps({
                "action": "create",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        elif action == "switch" and branch_name:
            result = _run_shell(f"git checkout {quote_cmd_arg(branch_name)}")
            return json.dumps({
                "action": "switch",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        else:
            return json.dumps({"error": f"Invalid action or missing branch_name: {action}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== Additional Git Operations ==========

def run_cmd(cmd: str, timeout: int = 300) -> str:
    """Run a shell command safely with security validation.

    Security:
        All commands are validated before execution. Shell metacharacters
        and non-allowlisted commands are rejected. No shell=True is used.

    Returns:
        JSON string with execution results
    """
    # Short-circuit repeated git clones to an existing destination
    try:
        tokens = shlex.split(cmd)
        if len(tokens) >= 2 and tokens[0] == "git" and tokens[1] == "clone":
            # Identify destination directory if explicitly provided
            # git clone <url> [directory]
            # Ignore options/flags
            args = [t for t in tokens[2:] if not t.startswith("-")]
            dest: Optional[str] = None
            if len(args) >= 2:
                # directory was provided after url
                dest = args[1]
            elif len(args) == 1:
                # only url was provided, dest is basename of url
                url = args[0]
                dest = url.rstrip("/").split("/")[-1].replace(".git", "")

            if dest:
                dest_path = pathlib.Path(dest)
                if not dest_path.is_absolute():
                    # Use module-level ROOT to respect monkeypatching in tests
                    dest_path = ROOT / dest_path

                if dest_path.exists():
                    return json.dumps({
                        "skipped": True,
                        "reason": "destination already exists; skipping git clone",
                        "path": str(dest_path),
                        "cmd": cmd,
                        "rc": 0,
                    })
    except (ValueError, IndexError):
        # If parsing fails, let command_runner handle it
        pass

    # Use safe command runner
    from rev.tools.command_runner import run_command_safe
    result = run_command_safe(
        cmd,
        timeout=timeout,
        capture_output=True,
        check_interrupt=True,
    )
    return json.dumps(result)


def run_tests(cmd: str = "pytest -q", timeout: int = 600) -> str:
    """Run test suite safely with security validation.

    Security:
        All commands are validated before execution. Shell metacharacters
        and non-allowlisted commands are rejected. No shell=True is used.

    Returns:
        JSON string with execution results
    """
    from rev.tools.command_runner import run_command_safe

    result = run_command_safe(
        cmd,
        timeout=timeout,
        capture_output=True,
        check_interrupt=True,
    )
    return json.dumps(result)


def _get_detailed_file_structure(root_path=None, max_depth: int = 2, max_files: int = 50):
    """Get detailed file structure for the repository.

    Args:
        root_path: Root directory to scan (defaults to repo root)
        max_depth: Maximum directory depth to scan
        max_files: Maximum number of files to list

    Returns:
        List of file info dicts with paths and types
    """
    if root_path is None:
        root_path = config.ROOT

    from rev.config import EXCLUDE_DIRS
    file_list = []

    def scan_dir(path, depth=0):
        if depth > max_depth or len(file_list) >= max_files:
            return

        try:
            for item in sorted(path.iterdir()):
                if item.name.startswith('.'):
                    continue
                if item.name in EXCLUDE_DIRS:
                    continue

                rel_path = str(item.relative_to(root_path))
                file_type = "directory" if item.is_dir() else "file"

                file_list.append({
                    "path": rel_path,
                    "type": file_type,
                    "depth": depth
                })

                if item.is_dir() and depth < max_depth:
                    scan_dir(item, depth + 1)
        except (PermissionError, OSError):
            pass

    scan_dir(root_path)
    return file_list


def get_repo_context(commits: int = 6) -> str:
    """Get repository context with detailed file structure."""
    from rev.cache import get_repo_cache

    # Try to get from cache first
    repo_cache = get_repo_cache()
    if repo_cache is not None:
        cached_context = repo_cache.get_context()
        if cached_context is not None:
            return cached_context

    # Generate context
    if is_git_repo():
        st = _run_shell("git status -s")
        lg = _run_shell(f"git log -n {int(commits)} --oneline")

        # If git commands failed (e.g., low memory / paging file error), surface a minimal context and skip crashing.
        if st.returncode != 0 or lg.returncode != 0:
            error_msg = st.stderr or lg.stderr or "git commands failed"
            return json.dumps({
                "status": st.stdout,
                "log": lg.stdout,
                "error": error_msg,
                "note": "git status/log unavailable (likely low memory); continuing with partial context",
            })
        
        status_out = st.stdout
        log_out = lg.stdout
    else:
        status_out = ""
        log_out = ""

    from rev.config import EXCLUDE_DIRS
    top = []
    for p in sorted(config.ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})

    # Include detailed file structure for better CodeWriterAgent context
    file_structure = _get_detailed_file_structure(max_depth=2, max_files=100)

    context = json.dumps({
        "status": status_out,
        "log": log_out,
        "top_level": top[:100],
        "file_structure": file_structure[:50],  # Include key files and directories
        "file_structure_note": "Key files in repository for reference when writing code"
    })

    # Cache it
    if repo_cache is not None:
        repo_cache.set_context(context)

    return context
