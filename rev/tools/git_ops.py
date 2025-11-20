#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Git operations tools for rev."""

import json
import os
import pathlib
import shlex
import subprocess
import tempfile
from typing import Optional

from rev.config import ROOT, ALLOW_CMDS


# ========== Helper Function ==========

def _run_shell(cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute shell command."""
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


# ========== Core Git Operations ==========

def git_diff(pathspec: str = ".", staged: bool = False, context: int = 3) -> str:
    """Get git diff for pathspec."""
    args = ["git", "diff", f"-U{context}"]
    if staged:
        args.insert(1, "--staged")
    if pathspec:
        args.append(pathspec)
    proc = _run_shell(" ".join(shlex.quote(a) for a in args))
    return json.dumps({"rc": proc.returncode, "diff": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})


def apply_patch(patch: str, dry_run: bool = False) -> str:
    """Apply a unified diff patch."""
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tf.write(patch)
        tf.flush()
        tfp = tf.name
    try:
        args = ["git", "apply"]
        if dry_run:
            args.append("--check")
        args.extend(["--3way", "--reject", tfp])
        proc = _run_shell(" ".join(shlex.quote(a) for a in args))
        return json.dumps({
            "rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "dry_run": dry_run
        })
    finally:
        try:
            os.unlink(tfp)
        except Exception:
            pass


def git_commit(message: str, files: str = ".") -> str:
    """Commit changes to git."""
    try:
        # Add files
        add_result = _run_shell(f"git add {shlex.quote(files)}")
        if add_result.returncode != 0:
            return json.dumps({"error": f"git add failed: {add_result.stderr}"})

        # Commit
        commit_result = _run_shell(f"git commit -m {shlex.quote(message)}")
        if commit_result.returncode != 0:
            return json.dumps({"error": f"git commit failed: {commit_result.stderr}"})

        return json.dumps({
            "committed": True,
            "message": message,
            "output": commit_result.stdout
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def git_status() -> str:
    """Get git status."""
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
            result = _run_shell(f"git branch {shlex.quote(branch_name)}")
            return json.dumps({
                "action": "create",
                "branch": branch_name,
                "returncode": result.returncode,
                "output": result.stdout
            })
        elif action == "switch" and branch_name:
            result = _run_shell(f"git checkout {shlex.quote(branch_name)}")
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
    """Run a shell command."""
    parts0 = shlex.split(cmd)[:1]
    ok = parts0 and (parts0[0] in ALLOW_CMDS or parts0[0] == "npx")
    if not ok:
        return json.dumps({"blocked": parts0, "allow": sorted(ALLOW_CMDS)})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        return json.dumps({
            "cmd": cmd,
            "rc": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-8000:]
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"timeout": timeout, "cmd": cmd})


def run_tests(cmd: str = "pytest -q", timeout: int = 600) -> str:
    """Run test suite."""
    p0 = shlex.split(cmd)[0]
    if p0 not in ALLOW_CMDS and p0 != "npx":
        return json.dumps({"blocked": p0})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        return json.dumps({
            "cmd": cmd,
            "rc": proc.returncode,
            "stdout": proc.stdout[-12000:],
            "stderr": proc.stderr[-4000:]
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"timeout": timeout, "cmd": cmd})


def get_repo_context(commits: int = 6) -> str:
    """Get repository context."""
    from rev.cache import get_repo_cache

    # Try to get from cache first
    repo_cache = get_repo_cache()
    if repo_cache is not None:
        cached_context = repo_cache.get_context()
        if cached_context is not None:
            return cached_context

    # Generate context
    st = _run_shell("git status -s")
    lg = _run_shell(f"git log -n {int(commits)} --oneline")

    from rev.config import EXCLUDE_DIRS
    top = []
    for p in sorted(ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})

    context = json.dumps({
        "status": st.stdout,
        "log": lg.stdout,
        "top_level": top[:100]
    })

    # Cache it
    if repo_cache is not None:
        repo_cache.set_context(context)

    return context
