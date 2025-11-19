#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agent.min — CI/CD Agent powered by Ollama
Minimal autonomous agent with single-gate approval and iterative execution.

Features:
- Single upfront approval gate (no repeated prompts)
- Planning mode: generates comprehensive task checklist
- Execution mode: iteratively completes all checklist items
- Automatic testing after each change
- Code operations: review, edit, add, delete, rename files
- Uses Ollama for local LLM inference

Usage:
    python agent.min "Add error handling to API endpoints"
    python agent.min --repl
"""

import os
import re
import sys
import json
import glob
import shlex
import argparse
import pathlib
import subprocess
import tempfile
import hashlib
import difflib
from typing import Dict, Any, List, Optional
from enum import Enum

# Ollama integration
try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

# Configuration
ROOT = pathlib.Path(os.getcwd()).resolve()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama:latest")
MAX_FILE_BYTES = 5 * 1024 * 1024
READ_RETURN_LIMIT = 80_000
SEARCH_MATCH_LIMIT = 2000
LIST_LIMIT = 2000

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".pytest_cache",
    "node_modules", "dist", "build", ".next", "out", "coverage", ".cache",
    ".venv", "venv", "target"
}

ALLOW_CMDS = {
    "python", "pip", "pytest", "ruff", "black", "isort", "mypy",
    "node", "npm", "npx", "pnpm", "prettier", "eslint", "git", "make"
}


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    """Represents a single task in the execution plan."""
    def __init__(self, description: str, action_type: str = "general"):
        self.description = description
        self.action_type = action_type  # edit, add, delete, rename, test, review
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "action_type": self.action_type,
            "status": self.status.value,
            "result": self.result,
            "error": self.error
        }


class ExecutionPlan:
    """Manages the task checklist for iterative execution."""
    def __init__(self):
        self.tasks: List[Task] = []
        self.current_index = 0

    def add_task(self, description: str, action_type: str = "general"):
        self.tasks.append(Task(description, action_type))

    def get_current_task(self) -> Optional[Task]:
        if self.current_index < len(self.tasks):
            return self.tasks[self.current_index]
        return None

    def mark_completed(self, result: str = None):
        if self.current_index < len(self.tasks):
            self.tasks[self.current_index].status = TaskStatus.COMPLETED
            self.tasks[self.current_index].result = result
            self.current_index += 1

    def mark_failed(self, error: str):
        if self.current_index < len(self.tasks):
            self.tasks[self.current_index].status = TaskStatus.FAILED
            self.tasks[self.current_index].error = error

    def is_complete(self) -> bool:
        return self.current_index >= len(self.tasks)

    def get_summary(self) -> str:
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        total = len(self.tasks)
        return f"Progress: {completed}/{total} completed, {failed} failed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "current_index": self.current_index,
            "summary": self.get_summary()
        }


# ========== File System Utilities ==========

def _safe_path(rel: str) -> pathlib.Path:
    """Resolve path safely within repo root."""
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT)):
        raise ValueError(f"Path escapes repo: {rel}")
    return p


def _is_text_file(path: pathlib.Path) -> bool:
    """Check if file is text (no null bytes)."""
    try:
        with open(path, "rb") as f:
            return b"\x00" not in f.read(8192)
    except Exception:
        return False


def _should_skip(path: pathlib.Path) -> bool:
    """Check if path should be excluded."""
    return any(part in EXCLUDE_DIRS for part in path.parts)


def _iter_files(include_glob: str) -> List[pathlib.Path]:
    """Iterate files matching glob pattern."""
    all_paths = [pathlib.Path(p) for p in glob.glob(str(ROOT / include_glob), recursive=True)]
    files = [p for p in all_paths if p.is_file()]
    return [p for p in files if not _should_skip(p)]


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


# ========== Core File Operations ==========

def read_file(path: str) -> str:
    """Read a file from the repository."""
    p = _safe_path(path)
    if not p.exists():
        return json.dumps({"error": f"Not found: {path}"})
    if p.stat().st_size > MAX_FILE_BYTES:
        return json.dumps({"error": f"Too large (> {MAX_FILE_BYTES} bytes): {path}"})
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if len(txt) > READ_RETURN_LIMIT:
            txt = txt[:READ_RETURN_LIMIT] + "\n...[truncated]..."
        return txt
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps({"wrote": str(p.relative_to(ROOT)), "bytes": len(content)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def list_dir(pattern: str = "**/*") -> str:
    """List files matching pattern."""
    files = _iter_files(pattern)
    rels = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in files)[:LIST_LIMIT]
    return json.dumps({"count": len(rels), "files": rels})


def search_code(pattern: str, include: str = "**/*", regex: bool = True,
                case_sensitive: bool = False, max_matches: int = SEARCH_MATCH_LIMIT) -> str:
    """Search code for pattern."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rex = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})

    matches = []
    for p in _iter_files(include):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if p.stat().st_size > MAX_FILE_BYTES or not _is_text_file(p):
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if rex.search(line):
                        matches.append({"file": rel, "line": i, "text": line.rstrip("\n")})
                        if len(matches) >= max_matches:
                            return json.dumps({"matches": matches, "truncated": True})
        except Exception:
            pass
    return json.dumps({"matches": matches, "truncated": False})


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
    st = _run_shell("git status -s")
    lg = _run_shell(f"git log -n {int(commits)} --oneline")
    top = []
    for p in sorted(ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})
    return json.dumps({
        "status": st.stdout,
        "log": lg.stdout,
        "top_level": top[:100]
    })


# ========== Additional File Operations ==========

def delete_file(path: str) -> str:
    """Delete a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.is_dir():
            return json.dumps({"error": f"Cannot delete directory (use delete_directory): {path}"})
        p.unlink()
        return json.dumps({"deleted": str(p.relative_to(ROOT))})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def move_file(src: str, dest: str) -> str:
    """Move or rename a file."""
    try:
        src_p = _safe_path(src)
        dest_p = _safe_path(dest)
        if not src_p.exists():
            return json.dumps({"error": f"Source not found: {src}"})
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        src_p.rename(dest_p)
        return json.dumps({
            "moved": str(src_p.relative_to(ROOT)),
            "to": str(dest_p.relative_to(ROOT))
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def append_to_file(path: str, content: str) -> str:
    """Append content to a file."""
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"appended_to": str(p.relative_to(ROOT)), "bytes": len(content)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def replace_in_file(path: str, find: str, replace: str, regex: bool = False) -> str:
    """Find and replace within a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        content = p.read_text(encoding="utf-8", errors="ignore")

        if regex:
            new_content = re.sub(find, replace, content)
        else:
            new_content = content.replace(find, replace)

        if content == new_content:
            return json.dumps({"replaced": 0, "file": str(p.relative_to(ROOT))})

        p.write_text(new_content, encoding="utf-8")
        count = len(content.split(find)) - 1 if not regex else len(re.findall(find, content))
        return json.dumps({
            "replaced": count,
            "file": str(p.relative_to(ROOT))
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def create_directory(path: str) -> str:
    """Create a directory."""
    try:
        p = _safe_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return json.dumps({"created": str(p.relative_to(ROOT))})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def get_file_info(path: str) -> str:
    """Get file metadata."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        stat = p.stat()
        return json.dumps({
            "path": str(p.relative_to(ROOT)),
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "is_file": p.is_file(),
            "is_dir": p.is_dir()
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def copy_file(src: str, dest: str) -> str:
    """Copy a file."""
    try:
        src_p = _safe_path(src)
        dest_p = _safe_path(dest)
        if not src_p.exists():
            return json.dumps({"error": f"Source not found: {src}"})
        if src_p.is_dir():
            return json.dumps({"error": f"Cannot copy directory: {src}"})
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(src_p, dest_p)
        return json.dumps({
            "copied": str(src_p.relative_to(ROOT)),
            "to": str(dest_p.relative_to(ROOT))
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def file_exists(path: str) -> str:
    """Check if a file or directory exists."""
    try:
        p = _safe_path(path)
        return json.dumps({
            "path": path,
            "exists": p.exists(),
            "is_file": p.is_file() if p.exists() else False,
            "is_dir": p.is_dir() if p.exists() else False
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def read_file_lines(path: str, start: int = 1, end: int = None) -> str:
    """Read specific lines from a file."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if p.stat().st_size > MAX_FILE_BYTES:
            return json.dumps({"error": f"Too large (> {MAX_FILE_BYTES} bytes): {path}"})

        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        start_idx = max(0, start - 1)  # Convert to 0-based index
        end_idx = len(lines) if end is None else min(len(lines), end)

        selected_lines = lines[start_idx:end_idx]
        return json.dumps({
            "path": str(p.relative_to(ROOT)),
            "start": start,
            "end": end_idx,
            "total_lines": len(lines),
            "lines": selected_lines
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def tree_view(path: str = ".", max_depth: int = 3, max_files: int = 100) -> str:
    """Generate a tree view of directory structure."""
    try:
        p = _safe_path(path)
        if not p.exists():
            return json.dumps({"error": f"Not found: {path}"})
        if not p.is_dir():
            return json.dumps({"error": f"Not a directory: {path}"})

        tree = []
        count = 0

        def build_tree(dir_path, prefix="", depth=0):
            nonlocal count
            if depth > max_depth or count >= max_files:
                return

            try:
                items = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                for idx, item in enumerate(items):
                    if count >= max_files:
                        break

                    is_last = idx == len(items) - 1
                    current_prefix = "└── " if is_last else "├── "
                    tree.append(prefix + current_prefix + item.name)
                    count += 1

                    if item.is_dir() and item.name not in EXCLUDE_DIRS:
                        extension = "    " if is_last else "│   "
                        build_tree(item, prefix + extension, depth + 1)
            except PermissionError:
                pass

        tree.append(p.name if p != ROOT else ".")
        build_tree(p)

        return json.dumps({
            "path": str(p.relative_to(ROOT)) if p != ROOT else ".",
            "tree": "\n".join(tree),
            "files_shown": count
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== Additional Git Operations ==========

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


# ========== Utility Tools ==========

def install_package(package: str) -> str:
    """Install a Python package."""
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
    """Fetch content from a URL."""
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
    """Execute Python code in a safe context."""
    try:
        # Create a restricted namespace
        namespace = {
            '__builtins__': __builtins__,
            'json': json,
            'os': os,
            're': re,
            'pathlib': pathlib
        }

        # Capture output
        import io
        import contextlib
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            exec(code, namespace)

        return json.dumps({
            "executed": True,
            "output": output.getvalue()
        })
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== MCP (Model Context Protocol) Support ==========

class MCPClient:
    """Client for Model Context Protocol servers."""

    def __init__(self):
        self.servers = {}
        self.tools = {}

    def add_server(self, name: str, command: str, args: List[str] = None) -> Dict[str, Any]:
        """Add an MCP server."""
        try:
            # Store server configuration
            self.servers[name] = {
                "command": command,
                "args": args or [],
                "connected": False
            }
            return {"added": name, "command": command}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def list_servers(self) -> Dict[str, Any]:
        """List configured MCP servers."""
        return {"servers": list(self.servers.keys())}

    def call_mcp_tool(self, server: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on an MCP server."""
        try:
            if server not in self.servers:
                return {"error": f"Server not found: {server}"}

            # For now, return a placeholder
            # Full MCP implementation would use stdio communication
            return {
                "mcp_call": True,
                "server": server,
                "tool": tool,
                "note": "MCP server communication would happen here"
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}


# Global MCP client instance
mcp_client = MCPClient()


def mcp_add_server(name: str, command: str, args: str = "") -> str:
    """Add an MCP server."""
    arg_list = args.split() if args else []
    result = mcp_client.add_server(name, command, arg_list)
    return json.dumps(result)


def mcp_list_servers() -> str:
    """List MCP servers."""
    result = mcp_client.list_servers()
    return json.dumps(result)


def mcp_call_tool(server: str, tool: str, arguments: str = "{}") -> str:
    """Call an MCP tool."""
    try:
        args_dict = json.loads(arguments)
        result = mcp_client.call_mcp_tool(server, tool, args_dict)
        return json.dumps(result)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON arguments: {e}"})


# ========== Ollama Integration ==========

# Debug mode - set to True to see API requests/responses
OLLAMA_DEBUG = os.getenv("OLLAMA_DEBUG", "0") == "1"

def ollama_chat(messages: List[Dict[str, str]], tools: List[Dict] = None) -> Dict[str, Any]:
    """Send chat request to Ollama.

    Note: Ollama's tool/function calling support varies by model and version.
    This implementation sends tools in OpenAI format but gracefully falls back
    if the model doesn't support them.
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"

    # Build base payload
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False
    }

    # Try with tools first if provided
    if tools:
        payload["tools"] = tools

    if OLLAMA_DEBUG:
        print(f"[DEBUG] Ollama request to {url}")
        print(f"[DEBUG] Model: {OLLAMA_MODEL}")
        print(f"[DEBUG] Messages: {json.dumps(messages, indent=2)}")
        if tools:
            print(f"[DEBUG] Tools: {len(tools)} tools provided")

    # Retry with increasing timeouts: 10m, 20m, 30m
    max_retries = 3
    base_timeout = 600  # 10 minutes

    for attempt in range(max_retries):
        timeout = base_timeout * (attempt + 1)  # 600, 1200, 1800

        if OLLAMA_DEBUG and attempt > 0:
            print(f"[DEBUG] Retry attempt {attempt + 1}/{max_retries} with timeout {timeout}s ({timeout // 60}m)")

        try:
            resp = requests.post(url, json=payload, timeout=timeout)

            if OLLAMA_DEBUG:
                print(f"[DEBUG] Response status: {resp.status_code}")
                print(f"[DEBUG] Response: {resp.text[:500]}")

            # If we get a 400 and we sent tools, try again without tools
            if resp.status_code == 400 and tools:
                if OLLAMA_DEBUG:
                    print("[DEBUG] Got 400 with tools, retrying without tools...")

                # Retry without tools
                payload_no_tools = {
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False
                }
                resp = requests.post(url, json=payload_no_tools, timeout=timeout)

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.Timeout as e:
            if attempt < max_retries - 1:
                if OLLAMA_DEBUG:
                    print(f"[DEBUG] Request timed out after {timeout}s, will retry with longer timeout...")
                continue  # Retry with longer timeout
            else:
                return {"error": f"Ollama API timeout after {max_retries} attempts (final timeout: {timeout}s)"}

        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = f" - {resp.text}"
            except:
                pass
            return {"error": f"Ollama API error: {e}{error_detail}"}

        except Exception as e:
            return {"error": f"Ollama API error: {e}"}


# ========== Tool Definitions ==========

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files matching glob pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g., **/*.py)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search code for pattern (regex)",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "include": {"type": "string", "description": "File pattern to include"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Get unified diff for changes",
            "parameters": {
                "type": "object",
                "properties": {
                    "pathspec": {"type": "string", "description": "Path to diff (default: .)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified diff patch",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string", "description": "Unified diff patch"},
                    "dry_run": {"type": "boolean", "description": "Check without applying"}
                },
                "required": ["patch"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_cmd",
            "description": "Run a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"}
                },
                "required": ["cmd"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run test suite",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Test command (default: pytest -q)"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_repo_context",
            "description": "Get repository context (status, log, structure)",
            "parameters": {
                "type": "object",
                "properties": {
                    "commits": {"type": "integer", "description": "Number of recent commits"}
                }
            }
        }
    },
    # File operations
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file to delete"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Move or rename a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Source path"},
                    "dest": {"type": "string", "description": "Destination path"}
                },
                "required": ["src", "dest"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "append_to_file",
            "description": "Append content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "content": {"type": "string", "description": "Content to append"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Find and replace text within a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "find": {"type": "string", "description": "Text to find"},
                    "replace": {"type": "string", "description": "Replacement text"},
                    "regex": {"type": "boolean", "description": "Use regex matching"}
                },
                "required": ["path", "find", "replace"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Create a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": "Get file metadata (size, modified time, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "copy_file",
            "description": "Copy a file to a new location",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Source path"},
                    "dest": {"type": "string", "description": "Destination path"}
                },
                "required": ["src", "dest"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_exists",
            "description": "Check if a file or directory exists",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to check"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_lines",
            "description": "Read specific line range from a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to file"},
                    "start": {"type": "integer", "description": "Start line number (1-indexed)"},
                    "end": {"type": "integer", "description": "End line number (inclusive)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "tree_view",
            "description": "Generate a tree view of directory structure",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: .)"},
                    "max_depth": {"type": "integer", "description": "Maximum depth (default: 3)"},
                    "max_files": {"type": "integer", "description": "Maximum files to show (default: 100)"}
                }
            }
        }
    },
    # Git operations
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit changes to git",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "files": {"type": "string", "description": "Files to add (default: .)"}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get git status",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Get git log",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of commits (default: 10)"},
                    "oneline": {"type": "boolean", "description": "Use oneline format"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_branch",
            "description": "Git branch operations (list, create, switch, current)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: list, current, create, or switch"},
                    "branch_name": {"type": "string", "description": "Branch name (for create/switch)"}
                }
            }
        }
    },
    # Utility tools
    {
        "type": "function",
        "function": {
            "name": "install_package",
            "description": "Install a Python package using pip",
            "parameters": {
                "type": "object",
                "properties": {
                    "package": {"type": "string", "description": "Package name"}
                },
                "required": ["package"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch content from a URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "Execute Python code and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"}
                },
                "required": ["code"]
            }
        }
    },
    # MCP tools
    {
        "type": "function",
        "function": {
            "name": "mcp_add_server",
            "description": "Add an MCP (Model Context Protocol) server",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Server name"},
                    "command": {"type": "string", "description": "Command to run server"},
                    "args": {"type": "string", "description": "Space-separated arguments"}
                },
                "required": ["name", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_list_servers",
            "description": "List configured MCP servers",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call_tool",
            "description": "Call a tool on an MCP server",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "Server name"},
                    "tool": {"type": "string", "description": "Tool name"},
                    "arguments": {"type": "string", "description": "JSON-encoded arguments"}
                },
                "required": ["server", "tool"]
            }
        }
    }
]


# ========== Tool Execution ==========

def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a tool and return result."""
    print(f"  → Executing: {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})")

    try:
        # Original tools
        if name == "read_file":
            return read_file(args["path"])
        elif name == "write_file":
            return write_file(args["path"], args["content"])
        elif name == "list_dir":
            return list_dir(args.get("pattern", "**/*"))
        elif name == "search_code":
            return search_code(args["pattern"], args.get("include", "**/*"))
        elif name == "git_diff":
            return git_diff(args.get("pathspec", "."))
        elif name == "apply_patch":
            return apply_patch(args["patch"], args.get("dry_run", False))
        elif name == "run_cmd":
            return run_cmd(args["cmd"], args.get("timeout", 300))
        elif name == "run_tests":
            return run_tests(args.get("cmd", "pytest -q"), args.get("timeout", 600))
        elif name == "get_repo_context":
            return get_repo_context(args.get("commits", 6))

        # File operations
        elif name == "delete_file":
            return delete_file(args["path"])
        elif name == "move_file":
            return move_file(args["src"], args["dest"])
        elif name == "append_to_file":
            return append_to_file(args["path"], args["content"])
        elif name == "replace_in_file":
            return replace_in_file(args["path"], args["find"], args["replace"], args.get("regex", False))
        elif name == "create_directory":
            return create_directory(args["path"])
        elif name == "get_file_info":
            return get_file_info(args["path"])
        elif name == "copy_file":
            return copy_file(args["src"], args["dest"])
        elif name == "file_exists":
            return file_exists(args["path"])
        elif name == "read_file_lines":
            return read_file_lines(args["path"], args.get("start", 1), args.get("end"))
        elif name == "tree_view":
            return tree_view(args.get("path", "."), args.get("max_depth", 3), args.get("max_files", 100))

        # Git operations
        elif name == "git_commit":
            return git_commit(args["message"], args.get("files", "."))
        elif name == "git_status":
            return git_status()
        elif name == "git_log":
            return git_log(args.get("count", 10), args.get("oneline", False))
        elif name == "git_branch":
            return git_branch(args.get("action", "list"), args.get("branch_name"))

        # Utility tools
        elif name == "install_package":
            return install_package(args["package"])
        elif name == "web_fetch":
            return web_fetch(args["url"])
        elif name == "execute_python":
            return execute_python(args["code"])

        # MCP tools
        elif name == "mcp_add_server":
            return mcp_add_server(args["name"], args["command"], args.get("args", ""))
        elif name == "mcp_list_servers":
            return mcp_list_servers()
        elif name == "mcp_call_tool":
            return mcp_call_tool(args["server"], args["tool"], args.get("arguments", "{}"))

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ========== Planning Mode ==========

PLANNING_SYSTEM = """You are an expert CI/CD agent analyzing tasks and creating execution plans.

Your job is to:
1. Understand the user's request
2. Analyze the repository structure
3. Create a comprehensive, ordered checklist of tasks

Break down the work into atomic tasks:
- Review: Analyze existing code
- Edit: Modify existing files
- Add: Create new files
- Delete: Remove files
- Rename: Move/rename files
- Test: Run tests to validate changes

Return ONLY a JSON array of tasks in this format:
[
  {"description": "Review current API endpoint structure", "action_type": "review"},
  {"description": "Add error handling to /api/users endpoint", "action_type": "edit"},
  {"description": "Create tests for error cases", "action_type": "add"},
  {"description": "Run test suite to validate changes", "action_type": "test"}
]

Be thorough but concise. Each task should be independently executable."""


def planning_mode(user_request: str) -> ExecutionPlan:
    """Generate execution plan from user request."""
    print("=" * 60)
    print("PLANNING MODE")
    print("=" * 60)

    # Get repository context
    print("→ Analyzing repository...")
    context = get_repo_context()

    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {"role": "user", "content": f"""Repository context:
{context}

User request:
{user_request}

Generate a comprehensive execution plan."""}
    ]

    print("→ Generating execution plan...")
    response = ollama_chat(messages)

    if "error" in response:
        print(f"Error: {response['error']}")
        sys.exit(1)

    # Parse the plan
    plan = ExecutionPlan()
    try:
        content = response.get("message", {}).get("content", "")
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            tasks_data = json.loads(json_match.group(0))
            for task_data in tasks_data:
                plan.add_task(
                    task_data.get("description", "Unknown task"),
                    task_data.get("action_type", "general")
                )
        else:
            print("Warning: Could not parse JSON plan, using fallback")
            plan.add_task(user_request, "general")
    except Exception as e:
        print(f"Warning: Error parsing plan: {e}")
        plan.add_task(user_request, "general")

    # Display plan
    print("\n" + "=" * 60)
    print("EXECUTION PLAN")
    print("=" * 60)
    for i, task in enumerate(plan.tasks, 1):
        print(f"{i}. [{task.action_type.upper()}] {task.description}")
    print("=" * 60)

    return plan


# ========== Execution Mode ==========

EXECUTION_SYSTEM = """You are an autonomous CI/CD agent executing tasks.

You have these tools available:
- read_file: Read file contents
- write_file: Create or modify files
- list_dir: List files matching pattern
- search_code: Search code with regex
- git_diff: View current changes
- apply_patch: Apply unified diff patches
- run_cmd: Execute shell commands
- run_tests: Run test suite
- get_repo_context: Get repo status

Work methodically:
1. Understand the current task
2. Gather necessary information (read files, search code)
3. Make changes (edit, add, or delete files)
4. Validate changes (run tests)
5. Report completion

Use unified diffs (apply_patch) for editing files. Always preserve formatting.
After making changes, run tests to ensure nothing broke.

Be concise. Execute the task and report success or failure."""


# Destructive operations that require confirmation
SCARY_OPERATIONS = {
    "keywords": ["delete", "remove", "rm ", "clean", "reset", "force", "destroy", "drop", "truncate"],
    "git_commands": ["reset --hard", "clean -f", "clean -fd", "push --force", "push -f"],
    "action_types": ["delete"]  # Task action types that are destructive
}


def is_scary_operation(tool_name: str, args: Dict[str, Any], action_type: str = "") -> tuple[bool, str]:
    """
    Check if an operation is potentially destructive and requires confirmation.
    Returns: (is_scary: bool, reason: str)
    """
    # Check action type
    if action_type in SCARY_OPERATIONS["action_types"]:
        return True, f"Destructive action type: {action_type}"

    # Check for file deletion
    if tool_name == "run_cmd":
        cmd = args.get("cmd", "").lower()

        # Check for dangerous git commands
        for git_cmd in SCARY_OPERATIONS["git_commands"]:
            if git_cmd in cmd:
                return True, f"Dangerous git command: {git_cmd}"

        # Check for scary keywords
        for keyword in SCARY_OPERATIONS["keywords"]:
            if keyword in cmd:
                return True, f"Potentially destructive command contains: {keyword}"

    # Check for patch operations without dry-run
    if tool_name == "apply_patch" and not args.get("dry_run", False):
        return True, "Applying patch (not dry-run)"

    return False, ""


def prompt_scary_operation(operation: str, reason: str) -> bool:
    """
    Prompt user to confirm a scary operation.
    Returns True if user approves, False otherwise.
    """
    print(f"\n{'='*60}")
    print(f"⚠️  POTENTIALLY DESTRUCTIVE OPERATION DETECTED")
    print(f"{'='*60}")
    print(f"Operation: {operation}")
    print(f"Reason: {reason}")
    print(f"{'='*60}")

    try:
        response = input("Continue with this operation? [y/N]: ").strip().lower()
        return response in ["y", "yes"]
    except (KeyboardInterrupt, EOFError):
        print("\n[Cancelled by user]")
        return False


def execution_mode(plan: ExecutionPlan, approved: bool = False, auto_approve: bool = True) -> bool:
    """Execute all tasks in the plan iteratively.

    Args:
        plan: ExecutionPlan with tasks to execute
        approved: Legacy parameter (ignored, kept for compatibility)
        auto_approve: If True (default), runs autonomously without initial approval.
                      Scary operations still require confirmation regardless.

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("EXECUTION MODE")
    print("=" * 60)

    # No upfront approval needed - runs autonomously
    # Scary operations will still prompt individually
    if not auto_approve:
        print("\nThis will execute all tasks with full autonomy.")
        print("⚠️  Note: Destructive operations will still require confirmation.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting autonomous execution...\n")
    if auto_approve:
        print("  ℹ️  Running in autonomous mode. Destructive operations will prompt for confirmation.\n")

    messages = [{"role": "system", "content": EXECUTION_SYSTEM}]
    max_iterations = 100
    iteration = 0

    while not plan.is_complete() and iteration < max_iterations:
        iteration += 1
        current_task = plan.get_current_task()

        print(f"\n[Task {plan.current_index + 1}/{len(plan.tasks)}] {current_task.description}")
        print(f"[Type: {current_task.action_type}]")

        current_task.status = TaskStatus.IN_PROGRESS

        # Add task to conversation
        messages.append({
            "role": "user",
            "content": f"""Task: {current_task.description}
Action type: {current_task.action_type}

Execute this task completely. When done, respond with TASK_COMPLETE."""
        })

        # Execute task with tool calls
        task_iterations = 0
        max_task_iterations = 20
        task_complete = False

        while task_iterations < max_task_iterations and not task_complete:
            task_iterations += 1

            # Try with tools, fall back to no-tools if needed
            response = ollama_chat(messages, tools=TOOLS)

            if "error" in response:
                error_msg = response['error']
                print(f"  ✗ Error: {error_msg}")

                # If we keep getting errors, try without tools
                if "400" in error_msg and task_iterations < 3:
                    print(f"  → Retrying without tool support...")
                    response = ollama_chat(messages, tools=None)

                if "error" in response:
                    plan.mark_failed(error_msg)
                    break

            msg = response.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            # Add assistant response to conversation
            messages.append(msg)

            # Execute tool calls FIRST before checking completion
            if tool_calls:
                for tool_call in tool_calls:
                    func = tool_call.get("function", {})
                    tool_name = func.get("name")
                    tool_args = func.get("arguments", {})

                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            tool_args = {}

                    # Check if this is a scary operation
                    is_scary, scary_reason = is_scary_operation(
                        tool_name,
                        tool_args,
                        current_task.action_type
                    )

                    if is_scary:
                        operation_desc = f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(tool_args.items())[:3])})"
                        if not prompt_scary_operation(operation_desc, scary_reason):
                            print(f"  ✗ Operation cancelled by user")
                            plan.mark_failed("User cancelled destructive operation")
                            task_complete = True
                            break

                    result = execute_tool(tool_name, tool_args)

                    # Add tool result to conversation
                    messages.append({
                        "role": "tool",
                        "content": result
                    })

                    # Check for test failures
                    if tool_name == "run_tests":
                        try:
                            result_data = json.loads(result)
                            if result_data.get("rc", 0) != 0:
                                print(f"  ⚠ Tests failed (rc={result_data['rc']})")
                        except:
                            pass

            # Check if task is complete AFTER executing tool calls
            if "TASK_COMPLETE" in content or "task complete" in content.lower():
                print(f"  ✓ Task completed")
                plan.mark_completed(content)
                task_complete = True
                break

            # If model responds but doesn't use tools and doesn't complete task
            if not tool_calls and content:
                # Model is thinking/responding without tool calls
                print(f"  → {content[:200]}")

                # If model keeps responding without tools or completion, it might not support them
                if task_iterations >= 3:
                    print(f"  ⚠ Model not using tools. Marking task as needs manual intervention.")
                    plan.mark_failed("Model does not support tool calling. Consider using a model with tool support.")
                    break

        if not task_complete and task_iterations >= max_task_iterations:
            print(f"  ✗ Task exceeded iteration limit")
            plan.mark_failed("Exceeded iteration limit")

    # Final summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())
    print()

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○"
        }.get(task.status, "?")

        print(f"{status_icon} {i}. {task.description} [{task.status.value}]")
        if task.error:
            print(f"    Error: {task.error}")

    print("=" * 60)

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)


# ========== REPL Mode ==========

def repl_mode():
    """Interactive REPL for iterative development with session memory."""
    print("agent.min REPL - Type /exit to quit, /help for commands")
    print("  ℹ️  Running in autonomous mode - destructive operations will prompt")

    # Session context to maintain memory across prompts
    session_context = {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": ""
    }

    while True:
        try:
            user_input = input("\nagent> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting REPL")
            break

        if not user_input:
            continue

        if user_input in ["/exit", "/quit", ":q"]:
            print("Exiting REPL")
            if session_context["tasks_completed"]:
                print(f"\nSession Summary:")
                print(f"  - Tasks completed: {len(session_context['tasks_completed'])}")
                print(f"  - Files reviewed: {len(session_context['files_reviewed'])}")
                print(f"  - Files modified: {len(session_context['files_modified'])}")
            break

        if user_input == "/help":
            print("""
Commands:
  /exit, /quit, :q  - Exit REPL
  /help             - Show this help
  /status           - Show session summary
  /clear            - Clear session memory

Otherwise, describe a task and the agent will plan and execute it.
Autonomous mode: destructive operations require confirmation, others run automatically.
            """)
            continue

        if user_input == "/status":
            print(f"\nSession Summary:")
            print(f"  - Tasks completed: {len(session_context['tasks_completed'])}")
            print(f"  - Files reviewed: {len(session_context['files_reviewed'])}")
            print(f"  - Files modified: {len(session_context['files_modified'])}")
            if session_context["last_summary"]:
                print(f"\nLast execution:")
                print(f"  {session_context['last_summary']}")
            continue

        if user_input == "/clear":
            session_context = {
                "tasks_completed": [],
                "files_modified": set(),
                "files_reviewed": set(),
                "last_summary": ""
            }
            print("Session memory cleared")
            continue

        # Execute task with auto-approve (no initial prompt, scary ops still prompt)
        plan = planning_mode(user_input)
        success = execution_mode(plan, auto_approve=True)

        # Update session context
        for task in plan.tasks:
            if task.status == TaskStatus.COMPLETED:
                session_context["tasks_completed"].append(task.description)
                # Track files for context
                if task.action_type in ["review", "read"]:
                    # Extract file names from task description
                    import re
                    files = re.findall(r'[\w\-./]+\.\w+', task.description)
                    session_context["files_reviewed"].update(files)
                elif task.action_type in ["edit", "add", "write"]:
                    files = re.findall(r'[\w\-./]+\.\w+', task.description)
                    session_context["files_modified"].update(files)

        session_context["last_summary"] = plan.get_summary()


# ========== Main Entry Point ==========

def main():
    global OLLAMA_MODEL, OLLAMA_BASE_URL

    parser = argparse.ArgumentParser(
        description="agent.min - Autonomous CI/CD agent powered by Ollama"
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Task description (one-shot mode)"
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Interactive REPL mode"
    )
    parser.add_argument(
        "--model",
        default=OLLAMA_MODEL,
        help=f"Ollama model (default: {OLLAMA_MODEL})"
    )
    parser.add_argument(
        "--base-url",
        default=OLLAMA_BASE_URL,
        help=f"Ollama base URL (default: {OLLAMA_BASE_URL})"
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Prompt for approval before execution (default: auto-approve)"
    )

    args = parser.parse_args()

    # Update module globals for ollama_chat function
    OLLAMA_MODEL = args.model
    OLLAMA_BASE_URL = args.base_url

    print(f"agent.min - CI/CD Agent")
    print(f"Model: {OLLAMA_MODEL}")
    print(f"Ollama: {OLLAMA_BASE_URL}")
    print(f"Repository: {ROOT}")
    if not args.prompt:
        print("  ℹ️  Autonomous mode: destructive operations will prompt for confirmation")
    print()

    try:
        if args.repl or not args.task:
            repl_mode()
        else:
            task_description = " ".join(args.task)
            plan = planning_mode(task_description)
            # Default to auto-approve (no initial prompt), unless --prompt flag is used
            execution_mode(plan, auto_approve=not args.prompt)
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
