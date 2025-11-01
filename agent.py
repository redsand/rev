def _add_del_from_patch_text(patch: str):
    adds = dels = 0
    files = []
    try:
        for line in patch.splitlines():
            if line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
                fp = line[4:].strip()
                if fp.startswith("b/"):
                    fp = fp[2:]
                if fp not in files:
                    files.append(fp)
                continue
            if not line or line.startswith(("--- ","+++ ","@@","diff --git")):
                continue
            if line.startswith("+"):
                adds += 1
            elif line.startswith("-"):
                dels += 1
    except Exception:
        pass
    return adds, dels, files

def _print_substatus(msg: str) -> None:
    if OUTPUT_STYLE == "claude":
        print(f"  ⎿ {msg}")
        return
    print(f"[STATUS] {msg}")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local Dev+Ops Agent — with interactive guard (C/A/S), SSH/SFTP, WinRM/PowerShell,
HTTP client, Bitwarden lookups, secret redaction, and REPL console.

Fixes included:
- Correct Chat Completions tool-calls sequencing (append assistant tool_calls message before tool results)
- Optional temperature (omit unless explicitly provided)
- http_request schema: json_body accepts object/null (arrays via 'data' string)
- SFTP single connect() with password OR key (no duplicate connects)
- Cleaned print strings (no stray newlines/backticks)

Usage
-----
python agent.py --repl
you> Use http_request to GET https://httpbin.org/json and summarize the title.
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
import getpass
import hashlib
import difflib
from typing import Dict, Any, List, Optional

# ---------- Optional deps (soft-imports) ----------
_REQ_ERR: Dict[str, str] = {}
try:
    import requests
except Exception as e:
    _REQ_ERR["requests"] = str(e)
try:
    import paramiko
except Exception as e:
    _REQ_ERR["paramiko"] = str(e)
try:
    import winrm  # pywinrm
except Exception as e:
    _REQ_ERR["pywinrm"] = str(e)
try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init()
    _HAS_COLOR = True
except Exception:
    _HAS_COLOR = False
COLOR_ENABLED = True

from openai import OpenAI


# ===== Add near your imports =====
from collections import deque

# ===== Add globals / config (top-level is fine) =====
HARD_LOCK_DEFAULT_MAX = int(os.getenv("AGENT_MAX_TOOL_CALLS_PER_TASK", "0"))
TOOL_REPEAT_WINDOW    = int(os.getenv("AGENT_TOOL_REPEAT_WINDOW", "3"))
TURN_CAP_TASK         = int(os.getenv("AGENT_TURN_CAP_TASK", "0"))
TURN_CAP_REPL         = int(os.getenv("AGENT_TURN_CAP_REPL", "0"))

API_MAX_CALLS_TASK    = int(os.getenv("AGENT_API_MAX_CALLS_PER_TASK", "0"))
API_MAX_TOKENS_TASK   = int(os.getenv("AGENT_API_MAX_TOKENS_PER_TASK", "0"))

API_MAX_CALLS_GLOBAL  = int(os.getenv("AGENT_API_MAX_CALLS_GLOBAL", "0"))   # 0 = disabled
API_MAX_TOKENS_GLOBAL = int(os.getenv("AGENT_API_MAX_TOKENS_GLOBAL", "0"))  # 0 = disabled
RESP_MAX_TOKENS       = int(os.getenv("AGENT_MAX_TOKENS_PER_RESPONSE", "0"))
ALLOW_TOOLS           = {t.strip() for t in os.getenv("AGENT_TOOL_ALLOWLIST", "").split(",") if t.strip()}
HARD_LOCK_AFTER_TOOL  = os.getenv("AGENT_HARD_LOCK_AFTER_TOOL", "0") == "1"
ASSUME_YES            = os.getenv("AGENT_ASSUME_YES", "0") == "1"
AUTO_CONTINUE         = os.getenv("AGENT_AUTO_CONTINUE", "1") == "1"
ALLOW_ALWAYS_REGEX    = [re.compile(p) for p in os.getenv("AGENT_ALLOW_ALWAYS_REGEX", "").split(",") if p.strip()]


_API_CALLS_GLOBAL = 0
_API_TOKENS_GLOBAL = 0

def _tok_usage_total(resp) -> int:
    try:
        u = getattr(resp, "usage", None)
        if not u:
            return 0
        # OpenAI python: u.total_tokens ; fallback dict
        return int(getattr(u, "total_tokens", 0) or (u.get("total_tokens", 0) if isinstance(u, dict) else 0))
    except Exception:
        return 0

def _tool_sig(name: str, args: dict) -> str:
    try:
        return f"{name}:{hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:12]}"
    except Exception:
        return f"{name}:na"

class _ToolGate:
    """Per-task tool gate with harder lock + repeat de-dupe + allowlist."""
    def __init__(self, max_calls: int, repeat_window: int):
        self.max_calls = max_calls
        self.calls = 0
        self.locked = False
        self.recent = deque(maxlen=repeat_window)

    def can_attempt(self) -> bool:
        return (not self.locked) and ((self.max_calls <= 0) or (self.calls < self.max_calls))
 
 
    def vet(self, name: str, args: dict):
        if self.locked:
            return False, "locked"
        if (self.max_calls > 0) and (self.calls >= self.max_calls):            
            return False, "tool_budget_exhausted"
        if ALLOW_TOOLS and name not in ALLOW_TOOLS:
            return False, f"not_allowed:{name}"
        sig = _tool_sig(name, args)
        if sig in self.recent:
            return False, "repeat_call"
        return True, sig

    def record(self, sig: str):
        self.recent.append(sig)
        self.calls += 1

    def hard_lock(self):
        self.locked = True



ROOT = pathlib.Path(os.getcwd()).resolve()

# ---------- Limits / filters ----------
MAX_FILE_BYTES       = 5 * 1024 * 1024
READ_RETURN_LIMIT    = 80_000
SEARCH_MATCH_LIMIT   = 2000
LIST_LIMIT           = 2000
PREFS_FILE           = ROOT / ".dev_agent_prefs.json"

EXCLUDE_DIRS = {
    ".git",".hg",".svn",".idea",".vscode","__pycache__",".pytest_cache",
    "node_modules","dist","build",".next","out","coverage",".cache",".venv","venv","target"
}

ALLOW_CMDS = {"python","pip","pytest","ruff","black","isort","mypy","node","npm","npx","pnpm","prettier","eslint","git","make"}

MUTATING_CMD_PATTERNS = [
    r"\bruff\b.*\b--fix\b",
    r"\bblack\b\b",
    r"\bisort\b\b",
    r"\bnpx\b\s+prettier\b.*\b(-w|--write)\b",
    r"\bnpx\b\s+eslint\b.*\b--fix\b",
    r"\bgit\b\s+(apply|checkout|merge|rebase|reset|mv|rm|commit)\b",
]

# ---------- Secret redaction ----------
REDACT: set[str] = set()
def _register_secret(val: Optional[str]):
    if not val:
        return
    try:
        REDACT.add(val)
        if len(val) > 8:
            REDACT.add(val[:4] + "..." + val[-4:])
    except Exception:
        pass

def _redact_text(s: Optional[str]) -> str:
    t = s or ""
    for secret in sorted(REDACT, key=len, reverse=True):
        if not secret:
            continue
        t = t.replace(secret, "********")
    return t

# ---------- Prefs (persisted) ----------
def _load_prefs() -> Dict[str, Any]:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"allow_always": []}

def _save_prefs(prefs: Dict[str, Any]) -> None:
    try:
        PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception:
        pass

PREFS = _load_prefs()

def _allowed_by_prefs(sig: str) -> bool:
    return sig in set(PREFS.get("allow_always", []))

def _remember_allow(sig: str) -> None:
    aa = set(PREFS.get("allow_always", []))
    aa.add(sig)
    PREFS["allow_always"] = sorted(aa)
    _save_prefs(PREFS)

# ---------- Helpers ----------
def _safe_path(rel: str) -> pathlib.Path:
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT)):
        raise ValueError(f"path escapes repo: {rel}")
    return p

def _is_text_file(path: pathlib.Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" not in f.read(8192)
    except Exception:
        return False

def _should_skip(path: pathlib.Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)

def _iter_files(include_glob: str) -> List[pathlib.Path]:
    all_paths = [pathlib.Path(p) for p in glob.glob(str(ROOT / include_glob), recursive=True)]
    files = [p for p in all_paths if p.is_file()]
    return [p for p in files if not _should_skip(p)]

def _run_shell(cmd: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)

def _hash_text(s: str) -> str:
    try:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]
    except Exception:
        return "na"

def _is_mutating_cmd(cmd: str) -> bool:
    return any(re.search(pat, cmd) for pat in MUTATING_CMD_PATTERNS)

# ---------- Interactive guard (C/A/S) ----------
def _print_guard_header(human_desc: str, preview: Optional[str]=None) -> None:
    if COLOR_ENABLED and _HAS_COLOR and sys.stdout.isatty():
        print(f"\n{Style.BRIGHT}{Fore.YELLOW}[GUARD]{Style.RESET_ALL} Pending change:\n  - {human_desc}")
        if preview:
            print(f"{Style.DIM}--- Preview ---{Style.RESET_ALL}\n{_redact_text(preview)}\n{Style.DIM}--- End Preview ---{Style.RESET_ALL}")
        print(f"Choose: {Style.BRIGHT}[C]{Style.RESET_ALL} Continue  |  {Style.BRIGHT}[A]{Style.RESET_ALL} Continue & don’t prompt again  |  {Style.BRIGHT}[S]{Style.RESET_ALL} Stop & provide instructions")
    else:
        print("\n[GUARD] Pending change:\n  - " + human_desc)
        if preview:
            print("--- Preview ---\n" + _redact_text(preview) + "\n--- End Preview ---")
        print("Choose: [C] Continue  |  [A] Continue & don’t prompt again  |  [S] Stop & provide instructions")

def _prompt_guard(action_sig: str, human_desc: str, non_interactive: bool, preview: Optional[str]=None) -> Dict[str, Any]:
    if _allowed_by_prefs(action_sig):
        return {"decision": "continue"}
    if ASSUME_YES:
        return {"decision": "continue"}
 
    # Regex auto-allow
    try:
        for rx in ALLOW_ALWAYS_REGEX:
            if rx.search(action_sig):
                return {"decision": "allow_always"}
    except Exception:
        pass

    if ASSUME_YES:
        return {"decision":"continue"}
    if non_interactive or not sys.stdin.isatty():
        if ASSUME_YES:
            return {"decision": "continue"}
        return {"decision": "stop", "reason": "Non-interactive mode; provide manual instructions."}


    _print_guard_header(human_desc, preview)
    try:
        while True:
            choice = input("Your choice (C/A/S): ").strip().lower()
            if choice in ("c", "a", "s"):
                break
        if choice == "c":
            return {"decision": "continue"}
        if choice == "a":
            _remember_allow(action_sig)
            print(f"[GUARD] Remembered: {action_sig}")
            return {"decision": "allow_always"}
        reason = input("Briefly describe what you want instead (optional): ").strip()
        return {"decision": "stop", "reason": (reason or "User requested instructions.")}
    except KeyboardInterrupt:
        print("\n[GUARD] Interrupted by Ctrl+C -> stopping")
        return {"decision": "stop", "reason": "Interrupted"}

# ---------- Core local tools ----------

def _print_status(msg: str) -> None:
    if COLOR_ENABLED and _HAS_COLOR and sys.stdout.isatty():
        print(f"{Style.DIM}{Fore.CYAN}[STATUS]{Style.RESET_ALL} {msg}")
    else:
        print(f"[STATUS] {msg}")

def _diff_preview(old_text: str, new_text: str, path: str) -> str:
    try:
        diff = difflib.unified_diff(
            (old_text or "").splitlines(),
            (new_text or "").splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm=""
        )
        preview = "\n".join(list(diff))
        if len(preview) > 8000:
            preview = preview[:8000] + "\n...[truncated]..."
        return preview
    except Exception:
        return "(diff preview unavailable)"

def _summarize_patch(patch: str) -> str:
    try:
        files = []
        for line in patch.splitlines():
            if line.startswith("diff --git "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    b_path = parts[3]
                    fp = (b_path[2:] if b_path.startswith("b/") else b_path)
                    if fp not in files:
                        files.append(fp)
            elif line.startswith("+++ "):
                fp = line[4:].strip()
                if fp != "/dev/null":
                    fp = fp[2:] if fp.startswith("b/") else fp
                    if fp not in files:
                        files.append(fp)
        head = "Files: " + (", ".join(files[:20]) or "(unknown)")
        body = patch
        if len(body) > 6000:
            body = body[:6000] + "\n...[truncated]..."
        return head + "\n\n" + body
    except Exception:
        return patch[:6000]

def read_file(path: str) -> str:
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

def write_file(path: str, content: str, non_interactive: bool=False) -> str:
    sig = f"write_file:{path}"
    # build preview of file changes
    try:
        p_prev = _safe_path(path)
        old = p_prev.read_text(encoding="utf-8", errors="ignore") if p_prev.exists() and p_prev.stat().st_size <= MAX_FILE_BYTES else ""
    except Exception:
        old = ""
    preview = _diff_preview(old, content, path)
    guard = _prompt_guard(sig, f"write_file -> {path} ({len(content)} bytes)", non_interactive, preview=preview)
    if guard["decision"] == "stop":
        return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return json.dumps({"wrote": str(p.relative_to(ROOT)), "bytes": len(content),
                       "always_allowed": guard["decision"] == "allow_always"})

def list_dir(pattern: str="**/*") -> str:
    files = _iter_files(pattern)
    rels = sorted(str(p.relative_to(ROOT)).replace("\\","/") for p in files)[:LIST_LIMIT]
    return json.dumps({"count": len(rels), "files": rels})

def run_cmd(cmd: str, timeout: int=300, non_interactive: bool=False) -> str:
    parts0 = shlex.split(cmd)[:1]
    ok = parts0 and (parts0[0] in ALLOW_CMDS or parts0[0] == "npx")
    if not ok:
        return json.dumps({"blocked": parts0, "allow": sorted(ALLOW_CMDS)})
    if _is_mutating_cmd(cmd):
        sig = f"run_cmd:{cmd}"
        guard = _prompt_guard(sig, f"run_cmd -> {cmd}", non_interactive)
        if guard["decision"] == "stop":
            return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        return json.dumps({"cmd": cmd, "rc": proc.returncode,
                           "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]})
    except subprocess.TimeoutExpired:
        return json.dumps({"timeout": timeout, "cmd": cmd})

# ---------- Search / Diff / Patch / Format / Tests / Context ----------

def search_code(pattern: str, include: str="**/*", exclude: Optional[List[str]]=None,
                regex: bool=True, case_sensitive: bool=False,
                max_matches: int=SEARCH_MATCH_LIMIT) -> str:
    exclude = exclude or []
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rex = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})
    matches = []
    for p in _iter_files(include):
        rel = str(p.relative_to(ROOT)).replace("\\","/")
        if any(glob.fnmatch.fnmatch(rel, ex) for ex in exclude):
            continue
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

def git_diff(pathspec: str=".", staged: bool=False, context: int=3) -> str:
    args = ["git", "diff", f"-U{context}"]
    if staged:
        args.insert(1, "--staged")
    if pathspec:
        args.append(pathspec)
    proc = _run_shell(" ".join(shlex.quote(a) for a in args))
    return json.dumps({"rc": proc.returncode, "diff": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})

def make_patch(paths: str=".") -> str:
    proc = _run_shell(f"git diff -U3 {shlex.quote(paths)}")
    return json.dumps({"rc": proc.returncode, "patch": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})

def apply_patch(patch: str, dry_run: bool=False, three_way: bool=True, reject: bool=True, non_interactive: bool=False) -> str:
    h = _hash_text(patch[:10000])
    sig = f"apply_patch:{h}"
    if not dry_run:
        preview = _summarize_patch(patch)
        guard = _prompt_guard(sig, f"apply_patch (apply) sha={h}", non_interactive, preview=preview)
        if guard["decision"] == "stop":
            return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tf.write(patch)
        tf.flush()
        tfp = tf.name
    try:
        args = ["git","apply"]
        if dry_run: args.append("--check")
        if three_way: args.append("--3way")
        if reject: args.append("--reject")
        args.append(tfp)
        proc = _run_shell(" ".join(shlex.quote(a) for a in args))
        return json.dumps({"rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "dry_run": dry_run})
    finally:
        try:
            os.unlink(tfp)
        except Exception:
            pass

def search_replace(pattern: str, replacement: str, include: str="**/*",
                   exclude: Optional[List[str]]=None, regex: bool=True, case_sensitive: bool=False,
                   dry_run: bool=True, non_interactive: bool=False) -> str:
    exclude = exclude or []
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rex = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})
    sig = f"search_replace:{pattern}|{replacement}|{include}|{','.join(exclude)}|regex={regex}|cs={case_sensitive}|dry={dry_run}"
    if not dry_run:
        guard = _prompt_guard(sig, f"search_replace (apply) pattern={pattern!r}", non_interactive)
        if guard["decision"] == "stop":
            return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    changed = []
    for p in _iter_files(include):
        rel = str(p.relative_to(ROOT)).replace("\\","/")
        if any(glob.fnmatch.fnmatch(rel, ex) for ex in exclude):
            continue
        if p.stat().st_size > MAX_FILE_BYTES or not _is_text_file(p):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
            new, n = rex.subn(replacement, txt)
            if n > 0:
                changed.append({"file": rel, "replacements": n})
                if not dry_run:
                    p.write_text(new, encoding="utf-8")
        except Exception:
            pass
    return json.dumps({"changed": changed, "dry_run": dry_run})

def format_code(tool: str="auto", non_interactive: bool=False) -> str:
    sig = f"format_code:{tool}"
    guard = _prompt_guard(sig, f"format_code -> {tool}", non_interactive)
    if guard["decision"] == "stop":
        return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    cmds = []
    if tool == "auto":
        cmds = ["ruff --fix .","black .","isort .","npx prettier -w .","npx eslint . --fix"]
    elif tool in {"ruff","black","isort"}:
        cmds = [f"{tool} ."]
    elif tool == "prettier":
        cmds = ["npx prettier -w ."]
    elif tool == "eslint":
        cmds = ["npx eslint . --fix"]
    else:
        return json.dumps({"error": f"Unknown formatter: {tool}"})
    results = []
    for c in cmds:
        p0 = shlex.split(c)[0]
        if p0 not in ALLOW_CMDS and p0 != "npx":
            continue
        proc = _run_shell(c)
        results.append({"cmd": c, "rc": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]})
    return json.dumps({"results": results})

def run_tests(cmd: str="pytest -q", timeout: int=600) -> str:
    p0 = shlex.split(cmd)[0]
    if p0 not in ALLOW_CMDS and p0 != "npx":
        return json.dumps({"blocked": p0})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        return json.dumps({"cmd": cmd, "rc": proc.returncode, "stdout": proc.stdout[-12000:], "stderr": proc.stderr[-4000:]})
    except subprocess.TimeoutExpired:
        return json.dumps({"timeout": timeout, "cmd": cmd})

def get_repo_context(commits: int=6) -> str:
    st = _run_shell("git status -s")
    lg = _run_shell(f"git log -n {int(commits)} --oneline")
    top = []
    for p in sorted(ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})
    return json.dumps({"status": st.stdout, "log": lg.stdout, "top_level": top[:100]})

# ---------- Bitwarden: vault lookups via CLI ----------

def bw_get(what: str, ref: str, field: Optional[str]=None) -> str:
    """
    what: 'password' | 'item' | 'username' | 'totp'
    ref : item id or name (as accepted by bw)
    field: for custom fields when what=='item' (optional)
    Requires: bw CLI logged-in & unlocked, BITWARDEN_SESSION exported.
    """
    bw_sess = os.environ.get("BITWARDEN_SESSION") or os.environ.get("BW_SESSION") or os.environ.get("BW_SESSION_TOKEN")
    if not bw_sess:
        return json.dumps({"error":"Bitwarden locked. Run 'bw login' then 'bw unlock' and export BITWARDEN_SESSION."})
    env = os.environ.copy()
    env["BW_SESSION"] = bw_sess

    if what in {"password","username","totp"}:
        proc = subprocess.run(["bw","get",what,ref], text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            return json.dumps({"error":proc.stderr.strip() or "bw get failed"})
        secret = proc.stdout.strip()
        _register_secret(secret)
        return json.dumps({what: "********"})
    elif what == "item":
        proc = subprocess.run(["bw","get","item",ref], text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            return json.dumps({"error":proc.stderr.strip() or "bw get item failed"})
        try:
            item = json.loads(proc.stdout)
            if item.get("login",{}).get("password"):
                _register_secret(item["login"]["password"])
            if item.get("login",{}).get("username"):
                _register_secret(item["login"]["username"])
            if field:
                val = None
                for f in (item.get("fields") or []):
                    if f.get("name") == field:
                        val = f.get("value","")
                        _register_secret(str(val))
                        val = "********"
                        break
                return json.dumps({"item": {"name": item.get("name"), "id": item.get("id")}, "field": field, "value": val})
            safe = {"name": item.get("name"), "id": item.get("id"), "login": {"username": "********" if item.get("login") else None}}
            return json.dumps({"item": safe})
        except Exception as e:
            return json.dumps({"error": f"Parse error: {e}"})
    else:
        return json.dumps({"error":"Unsupported 'what' for bw_get"})

# ---------- HTTP(S) client ----------

def http_request(method: str, url: str, headers: Optional[Dict[str,str]]=None, params: Optional[Dict[str,str]]=None,
                 json_body: Optional[Dict[str, Any]]=None, data: Optional[str]=None, timeout: int=30, verify_tls: bool=True,
                 bearer_token: Optional[str]=None, basic_user: Optional[str]=None, basic_pass: Optional[str]=None) -> str:
    """
    NOTE: json_body is OBJECT or null. For top-level JSON arrays, send 'data' as a raw string
    and set Content-Type: application/json in headers.
    """
    if "requests" in _REQ_ERR:
        return json.dumps({"error": f"requests not installed: {_REQ_ERR['requests']}"})
    headers = headers or {}
    params = params or {}
    if bearer_token:
        _register_secret(bearer_token)
        headers["Authorization"] = f"Bearer {bearer_token}"
    auth = None
    if basic_user is not None and basic_pass is not None:
        _register_secret(basic_user)
        _register_secret(basic_pass)
        auth = (basic_user, basic_pass)
    try:
        resp = requests.request(method.upper(), url, headers=headers, params=params,
                                json=json_body, data=data, timeout=timeout, verify=verify_tls, auth=auth)
        safe_headers = {k: ("********" if k.lower() in {"authorization","x-api-key"} else v) for k,v in resp.headers.items()}
        body = resp.text
        if len(body) > 12000:
            body = body[:12000] + "\n...[truncated]..."
        return json.dumps({"status": resp.status_code, "headers": safe_headers, "body": _redact_text(body)})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ---------- SSH exec + SFTP ----------

def ssh_exec(host: str, user: str, cmd: str, port: int=22, password: Optional[str]=None, key_path: Optional[str]=None,
             accept_unknown_host: bool=False, timeout: int=120, non_interactive: bool=False) -> str:
    if "paramiko" in _REQ_ERR:
        return json.dumps({"error": f"paramiko not installed: {_REQ_ERR['paramiko']}"})
    sig = f"ssh_exec:{user}@{host}:{port}:{cmd}"
    guard = _prompt_guard(sig, f"SSH {user}@{host}:{port} -> {cmd}", non_interactive)
    if guard["decision"] == "stop":
        return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    _register_secret(password)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy() if accept_unknown_host else paramiko.RejectPolicy())
        client.connect(hostname=host, port=port, username=user, password=password, key_filename=key_path, timeout=timeout)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out, err = stdout.read().decode(errors="ignore"), stderr.read().decode(errors="ignore")
        rc = stdout.channel.recv_exit_status()
        client.close()
        return json.dumps({"rc": rc, "stdout": out[-8000:], "stderr": err[-8000:]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

def sftp_put(host: str, user: str, local_path: str, remote_path: str, port: int=22, password: Optional[str]=None, key_path: Optional[str]=None,
             accept_unknown_host: bool=False, non_interactive: bool=False) -> str:
    if "paramiko" in _REQ_ERR:
        return json.dumps({"error": f"paramiko not installed: {_REQ_ERR['paramiko']}"})
    sig = f"sftp_put:{user}@{host}:{remote_path}"
    guard = _prompt_guard(sig, f"SFTP PUT {local_path} -> {user}@{host}:{remote_path}", non_interactive)
    if guard["decision"] == "stop":
        return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    _register_secret(password)
    try:
        lp = _safe_path(local_path)
        transport = paramiko.Transport((host, port))
        pkey = None
        if key_path:
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
        transport.connect(username=user, password=None if pkey else password, pkey=pkey)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(str(lp), remote_path)
        sftp.close()
        transport.close()
        return json.dumps({"ok": True, "bytes": pathlib.Path(lp).stat().st_size})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

def sftp_get(host: str, user: str, remote_path: str, local_path: str, port: int=22, password: Optional[str]=None, key_path: Optional[str]=None,
             accept_unknown_host: bool=False) -> str:
    if "paramiko" in _REQ_ERR:
        return json.dumps({"error": f"paramiko not installed: {_REQ_ERR['paramiko']}"})
    _register_secret(password)
    try:
        lp = _safe_path(local_path)
        lp.parent.mkdir(parents=True, exist_ok=True)
        transport = paramiko.Transport((host, port))
        pkey = None
        if key_path:
            pkey = paramiko.RSAKey.from_private_key_file(key_path)
        transport.connect(username=user, password=None if pkey else password, pkey=pkey)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get(remote_path, str(lp))
        sftp.close()
        transport.close()
        return json.dumps({"ok": True, "dest": str(lp.relative_to(ROOT))})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ---------- WinRM / PowerShell ----------

def winrm_exec(host: Optional[str]=None, endpoint: Optional[str]=None, command: Optional[str]=None, ps_script: Optional[str]=None,
               username: Optional[str]=None, password: Optional[str]=None, use_https: bool=True, port: int=5986,
               auth: str="ntlm", verify_tls: bool=False, timeout: int=120, non_interactive: bool=False) -> str:
    if "pywinrm" in _REQ_ERR:
        return json.dumps({"error": f"pywinrm not installed: {_REQ_ERR['pywinrm']}"})
    if not endpoint:
        if not host:
            return json.dumps({"error":"Provide host or endpoint"})
        scheme = "https" if use_https else "http"
        endpoint = f"{scheme}://{host}:{port}/wsman"
    sig = f"winrm_exec:{username}@{endpoint}:{'ps' if ps_script else 'cmd'}"
    guard = _prompt_guard(sig, f"WinRM -> {endpoint}", non_interactive)
    if guard["decision"] == "stop":
        return json.dumps({"user_decision":"stop","action_sig":sig,"reason":guard["reason"]})
    _register_secret(username)
    _register_secret(password)
    try:
        s = winrm.Session(endpoint, auth=(username, password),
                          transport=auth, server_cert_validation=('validate' if verify_tls else 'ignore'))
        if ps_script:
            r = s.run_ps(ps_script)
        else:
            if not command:
                return json.dumps({"error":"Provide command or ps_script"})
            r = s.run_cmd(command)
        out = (r.std_out or b"").decode(errors="ignore")
        err = (r.std_err or b"").decode(errors="ignore")
        return json.dumps({"rc": r.status_code, "stdout": out[-8000:], "stderr": err[-8000:]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ---------- OpenAI wiring ----------
one_round_rule = ("- You may chain small tool steps back-to-back until the current subtask is complete. "
                  "Do not pause for user confirmation unless the guard blocks or instructions are ambiguous.")
if not AUTO_CONTINUE:
    one_round_rule = ("- You may chain small tool steps back-to-back (plan → single tool call → reflect). "
                      "Do not batch multiple tool calls in one assistant turn.")


SYSTEM = f"""
You are a precise coding + ops agent working at repo: {ROOT}.

## Stepwise Build Protocol (STRICT)
- Work in **small, atomic steps**. For each cycle:
  1) PLAN the smallest next change (1 file or tiny set of lines).
  2) SHOW what you’ll change (file + lines) and why.
  3) APPLY the change using tools (prefer `apply_patch` with a unified diff).
  4) VALIDATE: run tests/lints minimally (e.g., `run_tests`).
  5) REPORT: summarize result and the **next** smallest step.
{one_round_rule}
- Prefer `search_code` → `git_diff` to inspect before editing.
- **Whitespace & indentation are sacred**:
  - Never “cleanup formatting” unless explicitly asked.
  - Preserve exact spacing and newlines in patches.
  - Use `apply_patch` (unified diff) for edits; avoid inline code dumps unless asked to show snippets.
  - After each patch, run `git diff --check` (via `run_cmd`) if needed to detect whitespace issues.
- Testing:
  - After each change, **run tests** (e.g., `run_tests` with pytest).
  - If failing, read the failure, patch the smallest fix, re-run tests.
  - Iterate until green or the change is clearly blocked.
- Safety:
  - For any mutating action, expect a human guard (Continue / Always / Stop).
  - Never print secrets; redact if seen. Use Bitwarden via `bw_get` when needed.

## Output Rules
- Keep responses compact.
- When proposing file edits, **use `apply_patch`** with a unified diff (`diff -u`/`git diff` style).
- If you must show code in chat, wrap it in triple backticks and **do not reformat or normalize indentation**.
- Do not run formatters (`black`, `prettier`, etc.) unless explicitly requested.
"""

# === Item 2: Strict Wrapper (adds stepwise enforcement to each user prompt) ===
STRICT_TASK_WRAPPER = """Follow the Stepwise Build Protocol (STRICT).
Work one tiny step at a time: plan → single tool call → validate tests → report next step.
Preserve whitespace exactly; use `apply_patch` unified diffs for edits; do not run formatters unless asked.

Task:
"""

TOOLS = [
    {"type":"function","function":{
        "name":"read_file","description":"Read a UTF-8 text file from the repo.",
        "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}
    }},
    {"type":"function","function":{
        "name":"write_file","description":"Create/overwrite a file (guarded).",
        "parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}
    }},
    {"type":"function","function":{
        "name":"list_dir","description":"List files (glob).",
        "parameters":{"type":"object","properties":{"pattern":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"run_cmd","description":"Run allowed shell command (guarded for mutating).",
        "parameters":{"type":"object","properties":{"cmd":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":1800}},"required":["cmd"]}
    }},
    {"type":"function","function":{
        "name":"search_code","description":"Search repo (regex by default).",
        "parameters":{"type":"object","properties":{"pattern":{"type":"string"},"include":{"type":"string"},"exclude":{"type":"array","items":{"type":"string"}},"regex":{"type":"boolean"},"case_sensitive":{"type":"boolean"},"max_matches":{"type":"integer"}},"required":["pattern"]}
    }},
    {"type":"function","function":{
        "name":"git_diff","description":"Unified diff for a pathspec.",
        "parameters":{"type":"object","properties":{"pathspec":{"type":"string"},"staged":{"type":"boolean"},"context":{"type":"integer"}}}
    }},
    {"type":"function","function":{
        "name":"make_patch","description":"Generate a git diff patch.",
        "parameters":{"type":"object","properties":{"paths":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"apply_patch","description":"Apply a unified diff via git apply (guarded).",
        "parameters":{"type":"object","properties":{"patch":{"type":"string"},"dry_run":{"type":"boolean"},"three_way":{"type":"boolean"},"reject":{"type":"boolean"}},"required":["patch"]}
    }},
    {"type":"function","function":{
        "name":"search_replace","description":"Multi-file replace (guarded if not dry_run).",
        "parameters":{"type":"object","properties":{"pattern":{"type":"string"},"replacement":{"type":"string"},"include":{"type":"string"},"exclude":{"type":"array","items":{"type":"string"}},"regex":{"type":"boolean"},"case_sensitive":{"type":"boolean"},"dry_run":{"type":"boolean"}},"required":["pattern","replacement"]}
    }},
    {"type":"function","function":{
        "name":"format_code","description":"Run formatters/linters (guarded).",
        "parameters":{"type":"object","properties":{"tool":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"run_tests","description":"Run tests.",
        "parameters":{"type":"object","properties":{"cmd":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":3600}}}
    }},
    {"type":"function","function":{
        "name":"get_repo_context","description":"Git status + recent commits + root tree.",
        "parameters":{"type":"object","properties":{"commits":{"type":"integer"}}}
    }},

    # Bitwarden + HTTP + Remote
    {"type":"function","function":{
        "name":"bw_get","description":"Bitwarden get (password/username/totp/item). Values are redacted.",
        "parameters":{"type":"object","properties":{"what":{"type":"string","enum":["password","username","totp","item"]},"ref":{"type":"string"},"field":{"type":"string"}},"required":["what","ref"]}
    }},
    {"type":"function","function":{
        "name":"http_request","description":"HTTP client (GET/POST/PUT/PATCH/DELETE).",
        "parameters":{"type":"object","properties":{
            "method":{"type":"string"},"url":{"type":"string"},
            "headers":{"type":"object","additionalProperties":{"type":"string"}},
            "params":{"type":"object","additionalProperties":{"type":"string"}},
            "json_body":{"type":["object","null"]},
            "data":{"type":["string","null"]},
            "timeout":{"type":"integer"},
            "verify_tls":{"type":"boolean"},
            "bearer_token":{"type":["string","null"]},
            "basic_user":{"type":["string","null"]},
            "basic_pass":{"type":["string","null"]}
        },"required":["method","url"]}}
    },
    {"type":"function","function":{
        "name":"ssh_exec","description":"Run a command over SSH (guarded).",
        "parameters":{"type":"object","properties":{
            "host":{"type":"string"},"user":{"type":"string"},"cmd":{"type":"string"},"port":{"type":"integer"},
            "password":{"type":["string","null"]},"key_path":{"type":["string","null"]},
            "accept_unknown_host":{"type":"boolean"},"timeout":{"type":"integer"}},
            "required":["host","user","cmd"]}
    }},
    {"type":"function","function":{
        "name":"sftp_put","description":"Upload a local file via SFTP (guarded).",
        "parameters":{"type":"object","properties":{
            "host":{"type":"string"},"user":{"type":"string"},"local_path":{"type":"string"},"remote_path":{"type":"string"},"port":{"type":"integer"},
            "password":{"type":["string","null"]},"key_path":{"type":["string","null"]},
            "accept_unknown_host":{"type":"boolean"}},
            "required":["host","user","local_path","remote_path"]}
    }},
    {"type":"function","function":{
        "name":"sftp_get","description":"Download a remote file via SFTP (read-only).",
        "parameters":{"type":"object","properties":{
            "host":{"type":"string"},"user":{"type":"string"},"remote_path":{"type":"string"},"local_path":{"type":"string"},"port":{"type":"integer"},
            "password":{"type":["string","null"]},"key_path":{"type":["string","null"]},
            "accept_unknown_host":{"type":"boolean"}},
            "required":["host","user","remote_path","local_path"]}
    }},
    {"type":"function","function":{
        "name":"winrm_exec","description":"Run a command or PowerShell script via WinRM (guarded).",
        "parameters":{"type":"object","properties":{
            "host":{"type":["string","null"]},"endpoint":{"type":["string","null"]},
            "command":{"type":["string","null"]},"ps_script":{"type":["string","null"]},
            "username":{"type":["string","null"]},"password":{"type":["string","null"]},
            "use_https":{"type":"boolean"},"port":{"type":"integer"},
            "auth":{"type":"string","enum":["ntlm","basic","kerberos"]},
            "verify_tls":{"type":"boolean"},"timeout":{"type":"integer"}}}
    }}
]

# ---------- Tool call routing ----------

def _handle_tool(name: str, args: Dict[str, Any], non_interactive: bool) -> str:
    def _tool_summary(name: str, args: Dict[str, Any]) -> str:
        try:
            if name == "write_file":
                return f"write_file -> {args.get('path')} ({len(args.get('content',''))} bytes)"
            if name == "apply_patch":
                ph = _hash_text((args.get('patch') or '')[:10000])
                return f"apply_patch sha={ph} dry_run={bool(args.get('dry_run', False))}"
            if name == "run_cmd":
                return f"run_cmd -> {args.get('cmd')}"
            if name == "http_request":
                return f"http_request -> {args.get('method','GET').upper()} {args.get('url')}"
            if name == "ssh_exec":
                return f"ssh_exec -> {args.get('user')}@{args.get('host')}:{args.get('port',22)}"
            if name == "sftp_put":
                return f"sftp_put -> {args.get('local_path')} => {args.get('user')}@{args.get('host')}:{args.get('remote_path')}"
            if name == "sftp_get":
                return f"sftp_get -> {args.get('user')}@{args.get('host')}:{args.get('remote_path')} => {args.get('local_path')}"
            if name == "winrm_exec":
                return f"winrm_exec -> endpoint={args.get('endpoint') or args.get('host')}"
            if name == "format_code":
                return f"format_code -> {args.get('tool','auto')}"
            if name == "run_tests":
                return f"run_tests -> {args.get('cmd','pytest -q')}"
            if name == "search_code":
                return f"search_code -> pattern={args.get('pattern')}"
            if name == "git_diff":
                return f"git_diff -> {args.get('pathspec','.')}"
            if name == "make_patch":
                return f"make_patch -> {args.get('paths','.')}"
            if name == "search_replace":
                return f"search_replace -> pattern={args.get('pattern')} include={args.get('include','**/*')}"
            if name == "list_dir":
                return f"list_dir -> {args.get('pattern','**/*')}"
            if name == "read_file":
                return f"read_file -> {args.get('path')}"
            if name == "get_repo_context":
                return f"get_repo_context -> commits={args.get('commits',6)}"
            if name == "bw_get":
                return f"bw_get -> {args.get('what')} {args.get('ref')}"
        except Exception:
            pass
        return name
    _print_status(_tool_summary(name, args))
    try:
        if name == "read_file":
            _res = read_file(args["path"])
            try:
                _data = json.loads(_res)
                if "error" in _data:
                    _print_substatus(f"Error: {_data['error']}")
                else:
                    _print_substatus("Read file.")
            except Exception:
                _print_substatus(f"Read {len(_res.splitlines())} lines")
            return _res
        if name == "write_file":        return write_file(args["path"], args["content"], non_interactive=non_interactive)
        if name == "list_dir":          return list_dir(args.get("pattern","**/*"))
        if name == "run_cmd":
            _res = run_cmd(args["cmd"], int(args.get("timeout",300)), non_interactive=non_interactive)
            try:
                _data = json.loads(_res)
                if "rc" in _data:
                    _print_substatus(f"rc={_data['rc']}")
            except Exception:
                pass
            return _res
        if name == "search_code":
            _res = search_code(args["pattern"], args.get("include","**/*"), args.get("exclude"), bool(args.get("regex",True)), bool(args.get("case_sensitive",False)), int(args.get("max_matches",SEARCH_MATCH_LIMIT)))
        if name == "git_diff":          return git_diff(args.get("pathspec","."), bool(args.get("staged",False)), int(args.get("context",3)))
        if name == "make_patch":        return make_patch(args.get("paths","."))
        if name == "apply_patch":
            _res = apply_patch(args["patch"], bool(args.get("dry_run",False)), bool(args.get("three_way",True)), bool(args.get("reject",True)), non_interactive=non_interactive)
        if name == "search_replace":    return search_replace(args["pattern"], args["replacement"], args.get("include","**/*"), args.get("exclude"), bool(args.get("regex",True)), bool(args.get("case_sensitive",False)), bool(args.get("dry_run",True)), non_interactive=non_interactive)
        if name == "format_code":       return format_code(args.get("tool","auto"), non_interactive=non_interactive)
        if name == "run_tests":
            _res = run_tests(args.get("cmd","pytest -q"), int(args.get("timeout",600)))
        if name == "get_repo_context":  return get_repo_context(int(args.get("commits",6)))
        # New
        if name == "bw_get":            return bw_get(args["what"], args["ref"], args.get("field"))
        if name == "http_request":      return http_request(args["method"], args["url"], args.get("headers"), args.get("params"), args.get("json_body"), args.get("data"), int(args.get("timeout",30)), bool(args.get("verify_tls",True)), args.get("bearer_token"), args.get("basic_user"), args.get("basic_pass"))
        if name == "ssh_exec":          return ssh_exec(args["host"], args["user"], args["cmd"], int(args.get("port",22)), args.get("password"), args.get("key_path"), bool(args.get("accept_unknown_host",False)), int(args.get("timeout",120)), non_interactive=non_interactive)
        if name == "sftp_put":          return sftp_put(args["host"], args["user"], args["local_path"], args["remote_path"], int(args.get("port",22)), args.get("password"), args.get("key_path"), bool(args.get("accept_unknown_host",False)), non_interactive=non_interactive)
        if name == "sftp_get":          return sftp_get(args["host"], args["user"], args["remote_path"], args["local_path"], int(args.get("port",22)), args.get("password"), args.get("key_path"), bool(args.get("accept_unknown_host",False)))
        if name == "winrm_exec":        return winrm_exec(args.get("host"), args.get("endpoint"), args.get("command"), args.get("ps_script"), args.get("username"), args.get("password"), bool(args.get("use_https",True)), int(args.get("port",5986)), args.get("auth","ntlm"), bool(args.get("verify_tls",False)), int(args.get("timeout",120)), non_interactive=non_interactive)
        return json.dumps({"error": f"unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ---------- Chat plumbing ----------

def load_api_key(cli_key: Optional[str], save_key: bool) -> str:
    if cli_key:
        key = cli_key
    elif os.getenv("OPENAI_API_KEY"):
        key = os.environ["OPENAI_API_KEY"]
    else:
        env_file = ROOT / ".dev_agent.env"
        key = ""
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("OPENAI_API_KEY="):
                        key = line.split("=",1)[1].strip()
                        break
            except Exception:
                key = ""
        if not key:
            if sys.stdin.isatty():
                key = getpass.getpass("Enter OPENAI_API_KEY: ").strip()
            else:
                raise RuntimeError("OPENAI_API_KEY not provided. Use --api-key or set env var.")
    if save_key:
        (ROOT / ".dev_agent.env").write_text(f"OPENAI_API_KEY={key}\n", encoding="utf-8")
    _register_secret(key)
    return key

def _chat_create(client: OpenAI, *, model: str, messages: List[Dict[str, Any]],
                 tools: List[Dict[str, Any]], tool_choice: str, temperature: Optional[float]):
    global _API_CALLS_GLOBAL, _API_TOKENS_GLOBAL

    if API_MAX_CALLS_GLOBAL and _API_CALLS_GLOBAL >= API_MAX_CALLS_GLOBAL:
        raise RuntimeError("Global API call cap reached")

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if RESP_MAX_TOKENS > 0:
        kwargs["max_completion_tokens"] = RESP_MAX_TOKENS

    resp = client.chat.completions.create(**kwargs)
    _API_CALLS_GLOBAL += 1
    used = _tok_usage_total(resp)
    if used:
        _API_TOKENS_GLOBAL += used
    if os.getenv("AGENT_VERBOSE") == "1":
        print(f"[Budget] Global calls={_API_CALLS_GLOBAL} tokens={_API_TOKENS_GLOBAL} (+{used})")
    return resp


def _append_assistant_with_tool_calls(messages: List[Dict[str, Any]], msg_obj: Any, max_calls: Optional[int]=None) -> None:
    tool_calls = list(msg_obj.tool_calls or [])
    if max_calls is not None:
        tool_calls = tool_calls[:max_calls]
    payload = []
    for tc in tool_calls:
        fn = tc.function
        payload.append({
            "id": tc.id,
            "type": "function",
            "function": {"name": fn.name, "arguments": fn.arguments or "{}"}
        })
    messages.append({"role": "assistant", "content": None, "tool_calls": payload})

# ===== Helper for per-task budgets =====
def _within_task_budget(task_calls: int, task_tokens: int) -> bool:
    if API_MAX_CALLS_TASK and task_calls >= API_MAX_CALLS_TASK:
        return False
    if API_MAX_TOKENS_TASK and task_tokens >= API_MAX_TOKENS_TASK:
        return False
    return True

# ===== Replace your _chat_once exactly =====
def _chat_once(prompt: str, model: str, client: OpenAI, non_interactive: bool,
               temperature: Optional[float], strict: bool) -> None:
    start_prompt = (STRICT_TASK_WRAPPER + prompt) if strict else prompt
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": start_prompt},
    ]

    gate = _ToolGate(HARD_LOCK_DEFAULT_MAX, TOOL_REPEAT_WINDOW)
    turn_cap = TURN_CAP_TASK
    turns = 0
    task_api_calls = 0
    task_tokens = 0

    while True:
        turns += 1
        if (turn_cap > 0) and (turns > turn_cap):
            print("[Guard] Stopping: exceeded task turn cap. Provide a smaller next step.")
            break
        if not _within_task_budget(task_api_calls, task_tokens):
            print("[Budget] Task cap reached (calls/tokens). Halting.")
            break

        tool_choice_mode = "auto" if gate.can_attempt() else "none"
        resp = _chat_create(client, model=model, messages=messages, tools=TOOLS,
                            tool_choice=tool_choice_mode, temperature=temperature)
        task_api_calls += 1
        task_tokens += _tok_usage_total(resp)

        msg = resp.choices[0].message
        if getattr(msg, "tool_calls", None):
            # Only allow ONE tool call per cycle, ignore parallels.
            tc = msg.tool_calls[0]
            _append_assistant_with_tool_calls(messages, msg, max_calls=1)

            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}

            allowed, note = gate.vet(name, args)
            if not allowed:
                # Return a synthetic tool result that blocks the call, then steer the model.
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"blocked": note, "hint": "Plan/validate and report. Do NOT call tools now."})
                })
                messages.append({"role": "system",
                                 "content": "Tool use is blocked. Provide validation or the next smallest step WITHOUT calling tools."})
                # Next loop will force tool_choice='none'
                continue

            # Execute the FIRST tool only.
            result = _handle_tool(name, args, non_interactive=non_interactive)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            gate.record(note)

            # If guard asked to STOP, hard-lock tools hereafter.
            try:
                parsed = json.loads(result)
            except Exception:
                parsed = {}

            if parsed.get("user_decision") == "stop":
                gate.hard_lock() if HARD_LOCK_AFTER_TOOL else None
                messages.append({"role": "system",
                                 "content": "Mutating step was stopped. Provide step-by-step instructions; do NOT call tools."})
            else:
                messages.append({"role": "system",
                                 "content": "TOOL STEP COMPLETE. If more work remains, PLAN the next smallest step and call the appropriate tool."})
            # Continue (tool_choice will remain 'auto' if not locked)
            continue

        # Natural answer — print and finish the one-shot
        print(_redact_text(msg.content or ""))
        break

def repl(model: str, client: OpenAI, non_interactive: bool, temperature: Optional[float], strict: bool) -> None:
    print("Interactive dev+ops agent REPL. Type /exit to quit.")
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM}]

    while True:
        try:
            user = input("you> ").strip()
        except KeyboardInterrupt:
            print("\nExiting REPL (Ctrl+C)")
            return
        if user in {"/exit", ":q", "quit"}:
            print("Exiting REPL.")
            return
        if not user:
            continue

        user_content = (STRICT_TASK_WRAPPER + user) if strict else user
        messages.append({"role": "user", "content": user_content})

        gate = _ToolGate(HARD_LOCK_DEFAULT_MAX, TOOL_REPEAT_WINDOW)
        inner_turns = 0
        task_api_calls = 0
        task_tokens = 0

        while True:
            inner_turns += 1
            if (TURN_CAP_REPL > 0) and (inner_turns > TURN_CAP_REPL):
                print("[Guard] Stopping: exceeded REPL step cap for this prompt.")
                messages.append({"role": "assistant", "content": "Halting this step due to safety cap. Provide a smaller next step."})
                break
            if not _within_task_budget(task_api_calls, task_tokens):
                print("[Budget] Task cap reached (calls/tokens). Halting this prompt.")
                messages.append({"role": "assistant", "content": "Budget reached for this step. Summarize next steps without tools."})
                break

            tool_choice_mode = "auto" if gate.can_attempt() else "none"
            resp = _chat_create(client, model=model, messages=messages, tools=TOOLS,
                                tool_choice=tool_choice_mode, temperature=temperature)
            task_api_calls += 1
            task_tokens += _tok_usage_total(resp)

            msg = resp.choices[0].message
            if getattr(msg, "tool_calls", None):
                tc = msg.tool_calls[0]
                _append_assistant_with_tool_calls(messages, msg, max_calls=1)

                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}

                allowed, note = gate.vet(name, args)
                if not allowed:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"blocked": note, "hint": "Plan/validate and report. Do NOT call tools now."})
                    })
                    messages.append({"role": "system",
                                     "content": "Tool use is blocked. Provide validation or the next smallest step WITHOUT calling tools."})
                    continue

                result = _handle_tool(name, args, non_interactive=non_interactive)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                gate.record(note)

                try:
                    parsed = json.loads(result)
                except Exception:
                    parsed = {}
                if parsed.get("user_decision") == "stop":
                    gate.hard_lock() if HARD_LOCK_AFTER_TOOL else None
                    messages.append({"role": "system",
                                     "content": "Mutating step was stopped. Provide instructions only; do NOT call tools."})
                else:
                    messages.append({"role": "system",
                                     "content": "TOOL STEP COMPLETE. If more work remains, PLAN the next smallest step and call the appropriate tool."})
                continue

            print(_redact_text(msg.content or ""))
            messages.append({"role": "assistant", "content": msg.content or ""})
            break

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="Local dev+ops agent (SSH/WinRM/HTTP/Bitwarden) with guard + REPL.")
    ap.add_argument("task", nargs="*", help="One-shot task. Omit to use --repl.")
    ap.add_argument("--model", default="gpt-5", help="Model name")
    ap.add_argument("--api-key", help="API key; else env or .dev_agent.env")
    ap.add_argument("--save-key", action="store_true", help="Persist key to .dev_agent.env")
    ap.add_argument("--base-url", default=None, help="Custom API base URL (optional)")
    ap.add_argument("--repl", action="store_true", help="Interactive chat console")
    ap.add_argument("--yes", action="store_true", help="Non-interactive: auto-STOP mutating ops (prints instructions)")
    ap.add_argument("--temperature", type=float, default=None, help="Sampling temperature. Omit to use the model default.")
    ap.add_argument("--strict", action="store_true", help="Prepend a strict stepwise wrapper to each user prompt.")
    args = ap.parse_args()

    key = load_api_key(args.api_key, args.save_key)
    client = OpenAI(api_key=key, base_url=args.base_url) if args.base_url else OpenAI(api_key=key)

    try:
        if args.repl or not args.task:
            repl(args.model, client, non_interactive=args.yes, temperature=args.temperature, strict=args.strict)
        else:
            _chat_once(" ".join(args.task), args.model, client, non_interactive=args.yes, temperature=args.temperature, strict=args.strict)
    except KeyboardInterrupt:
        print("\nAborted by Ctrl+C")

if __name__ == "__main__":
    main()
