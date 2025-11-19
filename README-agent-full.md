# hawk-ops-ai — Local Dev+Ops Agent

Local-first Dev+Ops agent with an interactive guard (C/A/S), HTTP client, Bitwarden lookups, SSH/SFTP, WinRM/PowerShell, search/diff/patch helpers, and a REPL that speaks to OpenAI Chat Completions.

Highlights
- File ops: read/write files, search/replace, search code, git diff/make/apply patches
- Run tools: formatters/linters/tests via run_cmd helpers (ruff/black/isort/prettier/eslint/pytest)
- Networking: HTTP(S) client with JSON and auth helpers
- Secrets: Bitwarden CLI lookups with automatic secret redaction in output
- Remote: SSH exec, SFTP upload/download, WinRM/PowerShell execution
- Guard: interactive confirmation for mutating actions with “Always allow” memory
- REPL: interactive console, plus one-shot task mode

This repo centers on agent.py and minimal requirements.

## Requirements
- Python 3.10+
- pip

Optional (feature-specific):
- requests (HTTP) — included in requirements
- paramiko (SSH/SFTP) — included in requirements
- pywinrm (WinRM/PowerShell) — included in requirements
- Bitwarden CLI (bw) — for bw_get

## Install
```bash
# from the project root
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
. .venv/Scripts/Activate.ps1

pip install -r requirements.txt
```

## Configure OpenAI
Provide your API key by one of:
- Environment variable: OPENAI_API_KEY
- Local file: .dev_agent.env containing a line `OPENAI_API_KEY=sk-...`
- CLI: `python agent.py --api-key sk-... --save-key` (persists to .dev_agent.env)

You can also set a custom base URL with `--base-url` and choose a model with `--model` (default: gpt-5).

## Usage

REPL (interactive)
```bash
python agent.py --repl
```
Useful flags:
- `--strict`  Prepend a strict stepwise wrapper to your prompts
- `--yes`     Non-interactive: mutating ops will be stopped with printed instructions
- `--model`   Override model name (default: gpt-5)
- `--temperature`  Set sampling temperature (omit to use model default)
- `--base-url` Custom API base URL

One-shot task
```bash
python agent.py "Use http_request to GET https://httpbin.org/json and summarize the title."
```

CLI flags (summary)
- `--model` default gpt-5
- `--api-key` supply API key directly
- `--save-key` store the supplied key into .dev_agent.env
- `--base-url` custom API base URL (optional)
- `--repl` run interactive console
- `--yes` non-interactive guard mode (mutations stop with instructions)
- `--temperature` optional float; omit to use model default
- `--strict` prepend strict stepwise wrapper

## Interactive Guard (C/A/S)
Mutating actions (e.g., write files, apply patches, formatters, git apply/commit, SSH/SFTP/WinRM) trigger a guard:
- C: Continue once
- A: Always allow this signature (remembered in .dev_agent_prefs.json)
- S: Stop and provide manual instructions

Allowed commands for run_cmd are constrained (e.g., python, pip, pytest, ruff, black, isort, mypy, node, npm, npx, prettier, eslint, git, make). Potentially destructive git subcommands (apply/checkout/merge/rebase/reset/mv/rm/commit) are additionally guarded.

Secrets are automatically redacted from printed outputs.

## Examples

HTTP request
```text
Use http_request to GET https://httpbin.org/json and summarize the slideshow title.
```

Bitwarden lookups (redacted in output)
```text
Use bw_get to fetch the username for item "My Service".
Then call http_request with basic auth to https://example.com/api.
```

SSH execution
```text
SSH to example.com as ubuntu and run: uname -a
Accept the unknown host key, and use key at ~/.ssh/id_rsa.
```

SFTP upload/download
```text
Upload ./dist/app.tar.gz to example.com:/tmp/app.tar.gz via SFTP as ubuntu.
Then download /var/log/syslog from example.com to ./logs/syslog.
```

WinRM/PowerShell
```text
Run PowerShell on winhost: Get-ComputerInfo | Select-Object CsName, OsName
Use HTTPS on port 5986 with NTLM auth.
```

File edits with guard
```text
Open README.md and append a Quick Tips section outlining guard behavior and allowed commands.
```

Search/diff/patch
```text
Search the repo for the pattern "TODO" and show matching files and lines.
Show a unified git diff for the working tree.
Apply the following unified diff patch: (paste patch)
```

Tests and formatting
```text
Run pytest -q and summarize failures.
Format the code with ruff, black, and isort.
```

## Notes on behavior
- Large outputs are truncated for readability.
- For JSON arrays in HTTP requests, send raw JSON via the `data` field and set Content-Type accordingly (agent handles object bodies via `json_body`).
- Secret values seen via Bitwarden or credentials are redacted in subsequent prints.

## Project structure
- agent.py — agent implementation and tool wiring
- requirements.txt — runtime dependencies
- requirements-dev.txt — optional dev tools
- tests/ — minimal tests/examples

## Troubleshooting
- “Blocked command”: run_cmd only allows a curated list; the agent will print allowed commands or manual steps.
- “Bitwarden locked”: run `bw login`, then `bw unlock`, and export BITWARDEN_SESSION.
- “Guard stopped in non-interactive mode”: re-run without `--yes` or choose C/A/S interactively.

## License
MIT (or your choice). Update this file if you prefer another license.
