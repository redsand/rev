#!/usr/bin/env python3
"""
Local Dev+Ops Agent (status-enhanced copy)
- Adds real-time status updates while actions/tools run for better visibility.

This file is based on agent.py with instrumentation added.
"""

import os, re, sys, json, glob, shlex, argparse, pathlib, subprocess, tempfile, getpass, hashlib, datetime
from typing import Dict, Any, List

# ----- optional deps (soft import) -----
_REQ_ERR = {}
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

from openai import OpenAI

ROOT = pathlib.Path(os.getcwd()).resolve()

# ----- limits / filters -----
MAX_FILE_BYTES     = 5 * 1024 * 1024
READ_RETURN_LIMIT  = 80_000
SEARCH_MATCH_LIMIT = 2000
LIST_LIMIT         = 2000
PREFS_FILE         = ROOT / ".dev_agent_prefs.json"

EXCLUDE_DIRS = {
    ".git",".hg",".svn",".idea",".vscode","__pycache__",".pytest_cache",
    "node_modules","dist","build",".next","out","coverage",".cache",".venv","venv","target"
}
ALLOW_CMDS = {"python","pip","pytest","ruff","black","isort","mypy","node","npm","npx","pnpm","prettier","eslint","git","make"}
MUTATING_CMD_PATTERNS = [
    r"\bruff\b.*\b--fix\b", r"\bblack\b\b", r"\bisort\b\b",
    r"\bnpx\b\s+prettier\b.*\b(-w|--write)\b", r"\bnpx\b\s+eslint\b.*\b--fix\b",
    r"\bgit\b\s+(apply|checkout|merge|rebase|reset|mv|rm|commit)\b"
]

# ----- secret redaction -----
REDACT: set[str] = set()

def _register_secret(val: str | None):
    if not val:
        return
    REDACT.add(val)
    if len(val) > 8:
        REDACT.add(val[:4] + "..." + val[-4:])

def _redact_text(s: str | None) -> str:
    t = s or ""
    for secret in sorted(REDACT, key=len, reverse=True):
        t = t.replace(secret, "********")
    return t

# ----- status logging -----
STATUS_ENABLED = True

SENSITIVE_ARG_KEYS = {"bearer_token", "basic_pass", "password", "Authorization", "x-api-key", "api_key"}

def _fmt_ts():
    return datetime.datetime.now().strftime("%H:%M:%S")

def _status(msg: str):
    if not STATUS_ENABLED:
        return
    print(f"[{_fmt_ts()}] [STATUS] {_redact_text(str(msg))}")

# ----- prefs (persisted allow rules) -----

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

# ----- helpers -----

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

# ----- interactive guard (C/A/S) -----

def _prompt_guard(action_sig: str, human_desc: str, non_interactive: bool) -> Dict[str, Any]:
    if _allowed_by_prefs(action_sig):
        return {"decision": "continue"}
    if non_interactive or not sys.stdin.isatty():
        return {"decision": "stop", "reason": "Non-interactive mode; provide manual instructions."}

    print("\n[GUARD] Pending change:\n  -", human_desc)
    print("Choose: [C] Continue  |  [A] Continue & don’t prompt again  |  [S] Stop & provide instructions")
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
    return {"decision": "stop", "reason": reason or "User requested instructions."}

# ----- local tools -----

def read_file(path: str) -> str:
    _status(f"read_file -> {path}")
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


def write_file(path: str, content: str, non_interactive: bool = False) -> str:
    sig = f"write_file:{path}"
    _status(f"write_file pending -> {path} ({len(content)} bytes)")
    guard = _prompt_guard(sig, f"write_file -> {path} ({len(content)} bytes)", non_interactive)
    if guard["decision"] == "stop":
        _status(f"write_file stopped by guard for {path}")
        return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _status(f"write_file done -> {path}")
    return json.dumps({"wrote": str(p.relative_to(ROOT)), "bytes": len(content),
                       "always_allowed": guard["decision"] == "allow_always"})


def list_dir(pattern: str = "**/*") -> str:
    _status(f"list_dir -> pattern={pattern}")
    files = _iter_files(pattern)
    rels = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in files)[:LIST_LIMIT]
    return json.dumps({"count": len(rels), "files": rels})


def run_cmd(cmd: str, timeout: int = 300, non_interactive: bool = False) -> str:
    _status(f"run_cmd start -> {cmd}")
    parts0 = shlex.split(cmd)[:1]
    ok = parts0 and (parts0[0] in ALLOW_CMDS or parts0[0] == "npx")
    if not ok:
        _status(f"run_cmd blocked -> {parts0}")
        return json.dumps({"blocked": parts0, "allow": sorted(ALLOW_CMDS)})
    if _is_mutating_cmd(cmd):
        sig = f"run_cmd:{cmd}"
        guard = _prompt_guard(sig, f"run_cmd -> {cmd}", non_interactive)
        if guard["decision"] == "stop":
            _status(f"run_cmd stopped by guard -> {cmd}")
            return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        _status(f"run_cmd done -> {cmd} (rc={proc.returncode})")
        return json.dumps({"cmd": cmd, "rc": proc.returncode,
                           "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]})
    except subprocess.TimeoutExpired:
        _status(f"run_cmd timeout -> {cmd}")
        return json.dumps({"timeout": timeout, "cmd": cmd})

# ----- search / diff / patch / format / tests / context -----

def search_code(pattern: str, include: str = "**/*", exclude: List[str] | None = None,
                regex: bool = True, case_sensitive: bool = False,
                max_matches: int = SEARCH_MATCH_LIMIT) -> str:
    _status(f"search_code -> pattern={pattern} include={include}")
    exclude = exclude or []
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rex = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex: {e}"})
    matches = []
    for p in _iter_files(include):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
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


def git_diff(pathspec: str = ".", staged: bool = False, context: int = 3) -> str:
    _status(f"git_diff -> staged={staged} context={context} pathspec={pathspec}")
    args = ["git", "diff", f"-U{context}"]
    if staged:
        args.insert(1, "--staged")
    if pathspec:
        args.append(pathspec)
    proc = _run_shell(" ".join(shlex.quote(a) for a in args))
    return json.dumps({"rc": proc.returncode, "diff": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})


def make_patch(paths: str = ".") -> str:
    _status(f"make_patch -> paths={paths}")
    proc = _run_shell(f"git diff -U3 {shlex.quote(paths)}")
    return json.dumps({"rc": proc.returncode, "patch": proc.stdout[-120000:], "stderr": proc.stderr[-4000:]})


def apply_patch(patch: str, dry_run: bool = False, three_way: bool = True, reject: bool = True,
                non_interactive: bool = False) -> str:
    h = _hash_text(patch[:10000])
    _status(f"apply_patch -> sha={h} dry_run={dry_run}")
    sig = f"apply_patch:{h}"
    if not dry_run:
        guard = _prompt_guard(sig, f"apply_patch (apply) sha={h}", non_interactive)
        if guard["decision"] == "stop":
            _status("apply_patch stopped by guard")
            return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tf:
        tf.write(patch)
        tf.flush()
        tfp = tf.name
    try:
        args = ["git", "apply"]
        if dry_run: args.append("--check")
        if three_way: args.append("--3way")
        if reject: args.append("--reject")
        args.append(tfp)
        proc = _run_shell(" ".join(shlex.quote(a) for a in args))
        _status(f"apply_patch done rc={proc.returncode}")
        return json.dumps({"rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "dry_run": dry_run})
    finally:
        try:
            os.unlink(tfp)
        except Exception:
            pass


def search_replace(pattern: str, replacement: str, include: str = "**/*",
                   exclude: List[str] | None = None, regex: bool = True, case_sensitive: bool = False,
                   dry_run: bool = True, non_interactive: bool = False) -> str:
    _status(f"search_replace -> pattern={pattern} dry_run={dry_run}")
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
            _status("search_replace stopped by guard")
            return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    changed = []
    for p in _iter_files(include):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
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
    _status(f"search_replace changed {len(changed)} files")
    return json.dumps({"changed": changed, "dry_run": dry_run})


def format_code(tool: str = "auto", non_interactive: bool = False) -> str:
    _status(f"format_code -> tool={tool}")
    sig = f"format_code:{tool}"
    guard = _prompt_guard(sig, f"format_code -> {tool}", non_interactive)
    if guard["decision"] == "stop":
        _status("format_code stopped by guard")
        return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    cmds = []
    if tool == "auto":
        cmds = ["ruff --fix .", "black .", "isort .", "npx prettier -w .", "npx eslint . --fix"]
    elif tool in {"ruff", "black", "isort"}:
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
        results.append({"cmd": c, "rc": proc.returncode,
                        "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]})
    _status(f"format_code completed {len(results)} steps")
    return json.dumps({"results": results})


def run_tests(cmd: str = "pytest -q", timeout: int = 600) -> str:
    _status(f"run_tests -> cmd={cmd}")
    p0 = shlex.split(cmd)[0]
    if p0 not in ALLOW_CMDS and p0 != "npx":
        return json.dumps({"blocked": p0})
    try:
        proc = _run_shell(cmd, timeout=timeout)
        _status(f"run_tests done rc={proc.returncode}")
        return json.dumps({"cmd": cmd, "rc": proc.returncode,
                           "stdout": proc.stdout[-12000:], "stderr": proc.stderr[-4000:]})
    except subprocess.TimeoutExpired:
        _status(f"run_tests timeout for {cmd}")
        return json.dumps({"timeout": timeout, "cmd": cmd})


def get_repo_context(commits: int = 6) -> str:
    _status("get_repo_context")
    st = _run_shell("git status -s")
    lg = _run_shell(f"git log -n {int(commits)} --oneline")
    top = []
    for p in sorted(ROOT.iterdir()):
        if p.name in EXCLUDE_DIRS:
            continue
        top.append({"name": p.name, "type": ("dir" if p.is_dir() else "file")})
    return json.dumps({"status": st.stdout, "log": lg.stdout, "top_level": top[:100]})

# ----- Bitwarden (bw CLI) -----

def bw_get(what: str, ref: str, field: str | None = None) -> str:
    _status(f"bw_get -> what={what} ref={ref}")
    """
    what: 'password' | 'item' | 'username' | 'totp'
    ref : item id or name (bw-compatible)
    field: optional custom field name (when what == 'item')
    Requires: bw login && bw unlock; export BITWARDEN_SESSION (or BW_SESSION).
    """
    bw_sess = os.environ.get("BITWARDEN_SESSION") or os.environ.get("BW_SESSION") or os.environ.get("BW_SESSION_TOKEN")
    if not bw_sess:
        return json.dumps({"error": "Bitwarden locked. Run 'bw login' then 'bw unlock' and export BITWARDEN_SESSION."})
    env = os.environ.copy()
    env["BW_SESSION"] = bw_sess

    if what in {"password", "username", "totp"}:
        proc = subprocess.run(["bw", "get", what, ref], text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            return json.dumps({"error": proc.stderr.strip() or "bw get failed"})
        secret = proc.stdout.strip()
        _register_secret(secret)
        return json.dumps({what: "********"})  # do not reveal
    elif what == "item":
        proc = subprocess.run(["bw", "get", "item", ref], text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            return json.dumps({"error": proc.stderr.strip() or "bw get item failed"})
        try:
            item = json.loads(proc.stdout)
            if item.get("login", {}).get("password"):
                _register_secret(item["login"]["password"])
            if item.get("login", {}).get("username"):
                _register_secret(item["login"]["username"])
            if field:
                val = None
                for f in (item.get("fields") or []):
                    if f.get("name") == field:
                        val = f.get("value", "")
                        _register_secret(str(val))
                        val = "********"
                        break
                return json.dumps({"item": {"name": item.get("name"), "id": item.get("id")}, "field": field, "value": val})
            safe = {"name": item.get("name"), "id": item.get("id"), "login": {"username": "********" if item.get("login") else None}}
            return json.dumps({"item": safe})
        except Exception as e:
            return json.dumps({"error": f"Parse error: {e}"})
    else:
        return json.dumps({"error": "Unsupported 'what' for bw_get"})

# ----- HTTP client -----

def http_request(method: str, url: str, headers: Dict[str, str] | None = None, params: Dict[str, str] | None = None,
                 json_body: Dict[str, Any] | None = None, data: str | None = None, timeout: int = 30,
                 verify_tls: bool = True, bearer_token: str | None = None,
                 basic_user: str | None = None, basic_pass: str | None = None) -> str:
    """
    NOTE: json_body is OBJECT or null (no arrays in schema). For top-level array bodies, use 'data'
    as a raw JSON string with Content-Type: application/json.
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
    _status(f"http_request -> {method.upper()} {url}")
    try:
        resp = requests.request(method.upper(), url, headers=headers, params=params,
                                json=json_body, data=data, timeout=timeout, verify=verify_tls, auth=auth)
        safe_headers = {k: ("********" if k.lower() in {"authorization","x-api-key"} else v) for k, v in resp.headers.items()}
        body = resp.text
        if len(body) > 12000:
            body = body[:12000] + "\n...[truncated]..."
        _status(f"http_request done -> {method.upper()} {url} (status={resp.status_code})")
        return json.dumps({"status": resp.status_code, "headers": safe_headers, "body": _redact_text(body)})
    except Exception as e:
        _status(f"http_request error -> {method.upper()} {url}: {type(e).__name__}")
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ----- SSH / SFTP -----

def ssh_exec(host: str, user: str, cmd: str, port: int = 22, password: str | None = None, key_path: str | None = None,
             accept_unknown_host: bool = False, timeout: int = 120, non_interactive: bool = False) -> str:
    if "paramiko" in _REQ_ERR:
        return json.dumps({"error": f"paramiko not installed: {_REQ_ERR['paramiko']}"})
    sig = f"ssh_exec:{user}@{host}:{port}:{cmd}"
    _status(f"ssh_exec -> {user}@{host}:{port} {cmd}")
    guard = _prompt_guard(sig, f"SSH {user}@{host}:{port} -> {cmd}", non_interactive)
    if guard["decision"] == "stop":
        _status("ssh_exec stopped by guard")
        return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    _register_secret(password)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy() if accept_unknown_host else paramiko.RejectPolicy())
        client.connect(hostname=host, port=port, username=user, password=password, key_filename=key_path, timeout=timeout)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out, err = stdout.read().decode(errors="ignore"), stderr.read().decode(errors="ignore")
        rc = stdout.channel.recv_exit_status()
        client.close()
        _status(f"ssh_exec done rc={rc}")
        return json.dumps({"rc": rc, "stdout": out[-8000:], "stderr": err[-8000:]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def sftp_put(host: str, user: str, local_path: str, remote_path: str, port: int = 22, password: str | None = None,
             key_path: str | None = None, accept_unknown_host: bool = False, non_interactive: bool = False) -> str:
    if "paramiko" in _REQ_ERR:
        return json.dumps({"error": f"paramiko not installed: {_REQ_ERR['paramiko']}"})
    sig = f"sftp_put:{user}@{host}:{remote_path}"
    _status(f"sftp_put -> {local_path} to {user}@{host}:{remote_path}")
    guard = _prompt_guard(sig, f"SFTP PUT {local_path} -> {user}@{host}:{remote_path}", non_interactive)
    if guard["decision"] == "stop":
        _status("sftp_put stopped by guard")
        return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
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
        _status("sftp_put done")
        return json.dumps({"ok": True, "bytes": pathlib.Path(lp).stat().st_size})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def sftp_get(host: str, user: str, remote_path: str, local_path: str, port: int = 22, password: str | None = None,
             key_path: str | None = None, accept_unknown_host: bool = False) -> str:
    if "paramiko" in _REQ_ERR:
        return json.dumps({"error": f"paramiko not installed: {_REQ_ERR['paramiko']}"})
    _register_secret(password)
    _status(f"sftp_get -> {user}@{host}:{remote_path} to {local_path}")
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
        _status("sftp_get done")
        return json.dumps({"ok": True, "dest": str(lp.relative_to(ROOT))})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ----- WinRM / PowerShell -----

def winrm_exec(host: str | None = None, endpoint: str | None = None, command: str | None = None,
               ps_script: str | None = None, username: str | None = None, password: str | None = None,
               use_https: bool = True, port: int = 5986, auth: str = "ntlm",
               verify_tls: bool = False, timeout: int = 120, non_interactive: bool = False) -> str:
    if "pywinrm" in _REQ_ERR:
        return json.dumps({"error": f"pywinrm not installed: {_REQ_ERR['pywinrm']}"})
    if not endpoint:
        if not host:
            return json.dumps({"error": "Provide host or endpoint"})
        scheme = "https" if use_https else "http"
        endpoint = f"{scheme}://{host}:{port}/wsman"
    sig = f"winrm_exec:{username}@{endpoint}:{'ps' if ps_script else 'cmd'}"
    _status(f"winrm_exec -> endpoint={endpoint}")
    guard = _prompt_guard(sig, f"WinRM -> {endpoint}", non_interactive)
    if guard["decision"] == "stop":
        _status("winrm_exec stopped by guard")
        return json.dumps({"user_decision": "stop", "action_sig": sig, "reason": guard["reason"]})
    _register_secret(username)
    _register_secret(password)
    try:
        s = winrm.Session(endpoint, auth=(username, password),
                          transport=auth, server_cert_validation=('validate' if verify_tls else 'ignore'))
        if ps_script:
            r = s.run_ps(ps_script)
        else:
            if not command:
                return json.dumps({"error": "Provide command or ps_script"})
            r = s.run_cmd(command)
        out = (r.std_out or b"").decode(errors="ignore")
        err = (r.std_err or b"").decode(errors="ignore")
        _status(f"winrm_exec done rc={r.status_code}")
        return json.dumps({"rc": r.status_code, "stdout": out[-8000:], "stderr": err[-8000:]})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})

# ----- OpenAI wiring -----
SYSTEM = f"""
You are a precise coding + ops agent working at repo: {ROOT}
You can:
- edit files, run linters/tests;
- manage remote servers via SSH/SFTP and WinRM/PowerShell;
- call HTTP APIs; fetch secrets from Bitwarden.
Guardrail protocol:
- Before any mutating action (local or remote), runtime may prompt the user (C/A/S).
- If a tool returns "user_decision":"stop", STOP changes and produce clear manual instructions.
- Keep outputs compact; show minimal diffs/snippets and commands. Never print secrets.
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
        "name":"list_dir","description":"List files by glob (default **/*), excluding heavy dirs.",
        "parameters":{"type":"object","properties":{"pattern":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"run_cmd","description":"Run an allowed shell command (guarded for mutating).",
        "parameters":{"type":"object","properties":{"cmd":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":1800}},"required":["cmd"]}
    }},
    {"type":"function","function":{
        "name":"search_code","description":"Search code for a pattern (regex by default).",
        "parameters":{"type":"object","properties":{
            "pattern":{"type":"string"},"include":{"type":"string"},
            "exclude":{"type":"array","items":{"type":"string"}},
            "regex":{"type":"boolean"},"case_sensitive":{"type":"boolean"},
            "max_matches":{"type":"integer"}},"required":["pattern"]}
    }},
    {"type":"function","function":{
        "name":"git_diff","description":"Get a unified diff for a pathspec.",
        "parameters":{"type":"object","properties":{"pathspec":{"type":"string"},"staged":{"type":"boolean"},"context":{"type":"integer"}}}
    }},
    {"type":"function","function":{
        "name":"make_patch","description":"Generate a git diff patch.",
        "parameters":{"type":"object","properties":{"paths":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"apply_patch","description":"Apply a unified diff via git apply (guarded).",
        "parameters":{"type":"object","properties":{
            "patch":{"type":"string"},"dry_run":{"type":"boolean"},"three_way":{"type":"boolean"},"reject":{"type":"boolean"}},
            "required":["patch"]}
    }},
    {"type":"function","function":{
        "name":"search_replace","description":"Multi-file search/replace (guarded if not dry_run).",
        "parameters":{"type":"object","properties":{
            "pattern":{"type":"string"},"replacement":{"type":"string"},"include":{"type":"string"},
            "exclude":{"type":"array","items":{"type":"string"}},
            "regex":{"type":"boolean"},"case_sensitive":{"type":"boolean"},"dry_run":{"type":"boolean"}},
            "required":["pattern","replacement"]}
    }},
    {"type":"function","function":{
        "name":"format_code","description":"Run code formatters/linters (guarded).",
        "parameters":{"type":"object","properties":{"tool":{"type":"string"}}}
    }},
    {"type":"function","function":{
        "name":"run_tests","description":"Run tests (pytest or custom).",
        "parameters":{"type":"object","properties":{"cmd":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":3600}}}
    }},
    {"type":"function","function":{
        "name":"get_repo_context","description":"Return git status, recent commits, and a shallow tree.",
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
            "host":{"type":"string"},"user":{"type":"string"},"cmd":{"type":"string"},
            "port":{"type":"integer"},"password":{"type":["string","null"]},"key_path":{"type":["string","null"]},
            "accept_unknown_host":{"type":"boolean"},"timeout":{"type":"integer"}},
            "required":["host","user","cmd"]}
    }},
    {"type":"function","function":{
        "name":"sftp_put","description":"Upload a local file via SFTP (guarded).",
        "parameters":{"type":"object","properties":{
            "host":{"type":"string"},"user":{"type":"string"},"local_path":{"type":"string"},"remote_path":{"type":"string"},
            "port":{"type":"integer"},"password":{"type":["string","null"]},"key_path":{"type":["string","null"]},
            "accept_unknown_host":{"type":"boolean"}},
            "required":["host","user","local_path","remote_path"]}
    }},
    {"type":"function","function":{
        "name":"sftp_get","description":"Download a remote file via SFTP (read-only).",
        "parameters":{"type":"object","properties":{
            "host":{"type":"string"},"user":{"type":"string"},"remote_path":{"type":"string"},"local_path":{"type":"string"},
            "port":{"type":"integer"},"password":{"type":["string","null"]},"key_path":{"type":["string","null"]},
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


def _safe_args_for_status(args: Dict[str, Any]) -> Dict[str, Any]:
    # shallow copy; mask sensitive keys
    safe = {}
    for k, v in (args or {}).items():
        if k in SENSITIVE_ARG_KEYS:
            safe[k] = "********"
        else:
            safe[k] = v
    return safe


def _handle_tool(name: str, args: Dict[str, Any], non_interactive: bool) -> str:
    try:
        _status(f"TOOL start -> {name} args={_safe_args_for_status(args)}")
        if name == "read_file":         res = read_file(args["path"])
        elif name == "write_file":      res = write_file(args["path"], args["content"], non_interactive=non_interactive)
        elif name == "list_dir":        res = list_dir(args.get("pattern", "**/*"))
        elif name == "run_cmd":         res = run_cmd(args["cmd"], int(args.get("timeout", 300)), non_interactive=non_interactive)
        elif name == "search_code":     res = search_code(args["pattern"], args.get("include","**/*"), args.get("exclude"), bool(args.get("regex", True)), bool(args.get("case_sensitive", False)), int(args.get("max_matches", SEARCH_MATCH_LIMIT)))
        elif name == "git_diff":        res = git_diff(args.get("pathspec","."), bool(args.get("staged", False)), int(args.get("context", 3)))
        elif name == "make_patch":      res = make_patch(args.get("paths","."))
        elif name == "apply_patch":     res = apply_patch(args["patch"], bool(args.get("dry_run", False)), bool(args.get("three_way", True)), bool(args.get("reject", True)), non_interactive=non_interactive)
        elif name == "search_replace":  res = search_replace(args["pattern"], args["replacement"], args.get("include","**/*"), args.get("exclude"), bool(args.get("regex", True)), bool(args.get("case_sensitive", False)), bool(args.get("dry_run", True)), non_interactive=non_interactive)
        elif name == "format_code":     res = format_code(args.get("tool","auto"), non_interactive=non_interactive)
        elif name == "run_tests":       res = run_tests(args.get("cmd","pytest -q"), int(args.get("timeout", 600)))
        elif name == "get_repo_context":res = get_repo_context(int(args.get("commits", 6)))
        elif name == "bw_get":          res = bw_get(args["what"], args["ref"], args.get("field"))
        elif name == "http_request":    res = http_request(args["method"], args["url"], args.get("headers"), args.get("params"), args.get("json_body"), args.get("data"), int(args.get("timeout",30)), bool(args.get("verify_tls", True)), args.get("bearer_token"), args.get("basic_user"), args.get("basic_pass"))
        elif name == "ssh_exec":        res = ssh_exec(args["host"], args["user"], args["cmd"], int(args.get("port",22)), args.get("password"), args.get("key_path"), bool(args.get("accept_unknown_host", False)), int(args.get("timeout",120)), non_interactive=non_interactive)
        elif name == "sftp_put":        res = sftp_put(args["host"], args["user"], args["local_path"], args["remote_path"], int(args.get("port",22)), args.get("password"), args.get("key_path"), bool(args.get("accept_unknown_host", False)), non_interactive=non_interactive)
        elif name == "sftp_get":        res = sftp_get(args["host"], args["user"], args["remote_path"], args["local_path"], int(args.get("port",22)), args.get("password"), args.get("key_path"), bool(args.get("accept_unknown_host", False)))
        elif name == "winrm_exec":      res = winrm_exec(args.get("host"), args.get("endpoint"), args.get("command"), args.get("ps_script"), args.get("username"), args.get("password"), bool(args.get("use_https", True)), int(args.get("port",5986)), args.get("auth","ntlm"), bool(args.get("verify_tls", False)), int(args.get("timeout",120)), non_interactive=non_interactive)
        else:
            res = json.dumps({"error": f"unknown tool: {name}"})
        # summarize result
        try:
            obj = json.loads(res)
            if isinstance(obj, dict) and "error" in obj:
                _status(f"TOOL error -> {name}: {obj['error']}")
            else:
                # try to include key fields
                summary = {k: obj.get(k) for k in ("rc","status","wrote","ok","changed","matches") if isinstance(obj, dict) and k in obj}
                _status(f"TOOL done -> {name} summary={summary if summary else 'ok'}")
        except Exception:
            _status(f"TOOL done -> {name}")
        return res
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def load_api_key(cli_key: str | None, save_key: bool) -> str:
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
                        key = line.split("=", 1)[1].strip()
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
    return key


def _append_assistant_with_tool_calls(messages, msg):
    tool_calls_payload = []
    for tc in (msg.tool_calls or []):
        fn = tc.function
        tool_calls_payload.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": fn.name,
                "arguments": fn.arguments or "{}"
            }
        })
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": tool_calls_payload
    })


def _chat_once(prompt: str, model: str, client: OpenAI, non_interactive: bool, temperature: float | None):
    messages = [{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]
    _status(f"chat_once start -> model={model}")
    while True:
        resp = _chat_create(client, model=model, messages=messages, tools=TOOLS, tool_choice="auto", temperature=temperature)
        msg = resp.choices[0].message
        if getattr(msg, "tool_calls", None):
            _append_assistant_with_tool_calls(messages, msg)
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                _status(f"assistant requested tool -> {tc.function.name}")
                result = _handle_tool(tc.function.name, args, non_interactive=non_interactive)
                messages.append({"role":"tool", "tool_call_id": tc.id, "content": result})
            continue
        print(_redact_text(msg.content or ""))
        _status("chat_once done")
        break


def repl(model: str, client: OpenAI, non_interactive: bool, temperature: float | None):
    print("Interactive dev+ops agent REPL. Type /exit to quit.")
    messages = [{"role":"system","content":SYSTEM}]
    while True:
        user = input("you> ").strip()
        if user in {"/exit", ":q", "quit"}:
            break
        if not user:
            continue
        messages.append({"role":"user","content":user})
        while True:
            resp = _chat_create(client, model=model, messages=messages, tools=TOOLS, tool_choice="auto", temperature=temperature)
            msg = resp.choices[0].message
            if getattr(msg, "tool_calls", None):
                _append_assistant_with_tool_calls(messages, msg)
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    _status(f"assistant requested tool -> {tc.function.name}")
                    result = _handle_tool(tc.function.name, args, non_interactive=non_interactive)
                    messages.append({"role":"tool", "tool_call_id": tc.id, "content": result})
                continue
            print(_redact_text(msg.content or ""))
            messages.append({"role":"assistant","content": msg.content or ""})
            break


def _chat_create(client, *, model, messages, tools, tool_choice, temperature):
    kwargs = {"model": model, "messages": messages, "tools": tools, "tool_choice": tool_choice}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return client.chat.completions.create(**kwargs)


def main():
    ap = argparse.ArgumentParser(description="Local dev+ops agent (SSH/WinRM/HTTP/Bitwarden) with guard + REPL + status.")
    ap.add_argument("task", nargs="*", help="One-shot task (omit to use --repl).")
    ap.add_argument("--model", default="gpt-5", help="Model name")
    ap.add_argument("--temperature", type=float, default=None, help="Sampling temperature")
    ap.add_argument("--api-key", help="API key; else env or .dev_agent.env")
    ap.add_argument("--save-key", action="store_true", help="Persist key to .dev_agent.env")
    ap.add_argument("--base-url", default=None, help="Custom API base URL (optional)")
    ap.add_argument("--repl", action="store_true", help="Interactive chat console")
    ap.add_argument("--yes", action="store_true", help="Non-interactive: auto-STOP mutating ops (prints instructions)")
    ap.add_argument("--no-status", action="store_true", help="Disable status lines")
    args = ap.parse_args()

    global STATUS_ENABLED
    STATUS_ENABLED = not args.no_status

    key = load_api_key(args.api_key, args.save_key)
    client = OpenAI(api_key=key, base_url=args.base_url) if args.base_url else OpenAI(api_key=key)

    if args.repl or not args.task:
        repl(args.model, client, non_interactive=args.yes, temperature=args.temperature)
    else:
        _chat_once(" ".join(args.task), args.model, client, non_interactive=args.yes, temperature=args.temperature)

if __name__ == "__main__":
    main()
