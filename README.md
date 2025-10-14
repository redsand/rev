# hawk-ops-ai — Local Dev+Ops Agent

A lightweight, local-first Dev+Ops helper that can:
- edit files, run formatters/linters/tests
- make HTTP calls
- connect to remote hosts via SSH/SFTP and WinRM/PowerShell
- fetch secrets from Bitwarden (bw CLI)
- apply a built-in guard so mutating actions can be confirmed (C/A/S)

This repo contains a single executable agent (agent.py) and a minimal requirements.txt.

## Requirements
- Python 3.10+
- pip

Optional (only if you need the features):
- requests (HTTP) — included in requirements
- paramiko (SSH/SFTP) — included in requirements
- pywinrm (WinRM/PowerShell) — included in requirements
- Bitwarden CLI (bw) if you want bw_get

## Install
```bash
# from the project root
python -m venv .venv
. .venv/Scripts/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure OpenAI
Provide your API key via one of:
- Environment variable: set OPENAI_API_KEY
- A local file: .dev_agent.env with a line `OPENAI_API_KEY=sk-...`
- CLI: `python agent.py --api-key sk-... --save-key` to persist into .dev_agent.env

## Quick start (REPL)
```bash
python agent.py --repl
```
Then type natural-language tasks. Examples:
- "Use http_request to GET https://httpbin.org/json and summarize the title"
- "Initialize a git repo and add a README with usage examples"
- "SSH to host and run uptime" (you will be prompted; never print secrets)

## One-shot tasks
You can also run a single task without entering the REPL:
```bash
python agent.py "Use http_request to GET https://httpbin.org/json and print the slideshow title"
```

## Examples
- HTTP request
  - Ask: "GET https://httpbin.org/json and summarize the title"
  - The agent will call the http_request tool and produce a short summary.

- File changes with guard
  - The agent may prompt before mutating operations. Choices:
    - C: Continue once
    - A: Always allow this signature (remembered in .dev_agent_prefs.json)
    - S: Stop and print manual instructions

- Remote access
  - SSH/SFTP (paramiko), WinRM/PowerShell (pywinrm)
  - The agent masks secrets in outputs. Supply credentials via environment, Bitwarden, or prompts.

## Project structure
- agent.py — the agent implementation
- requirements.txt — dependencies

## Troubleshooting
- If a command is blocked, the agent prints allowed commands or manual steps.
- For large outputs, content may be truncated.
- If Bitwarden is locked, run `bw login` then `bw unlock` and export `BITWARDEN_SESSION`.

## License
MIT (or your choice). Update this file if you prefer another license.
