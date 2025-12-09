# Private Mode for MCP Servers

Private mode is a security feature that disables all public MCP servers when working with confidential or proprietary code.

## What is Private Mode?

When private mode is enabled:
- ✅ All **public** MCP servers are disabled (DEFAULT_MCP_SERVERS, REMOTE_MCP_SERVERS)
- ✅ Only **user-configured** servers with API keys remain available
- ✅ Code and data are not sent to external services
- ✅ Local development continues without external dependencies

## When to Use Private Mode

Use private mode when:
- Working with proprietary/confidential code
- Handling sensitive data or credentials
- Working on air-gapped or secure networks
- Company policy prohibits external service usage
- Debugging security-sensitive features

## How to Enable Private Mode

### Method 1: Environment Variable (Permanent)

Set the environment variable before starting rev:

```bash
export REV_PRIVATE_MODE=true
python -m rev
```

Or add to your `.env` file:
```bash
# .env
REV_PRIVATE_MODE=true
```

### Method 2: Programmatic (Runtime Toggle)

Enable/disable private mode at runtime:

```python
from rev.mcp import mcp_enable_private_mode, mcp_disable_private_mode, mcp_get_private_mode_status
import json

# Enable private mode
result = mcp_enable_private_mode()
print(json.dumps(json.loads(result), indent=2))
# Output:
# {
#   "private_mode": true,
#   "disabled_servers": 8,
#   "active_servers": [],
#   "message": "Private mode enabled. 8 public MCP servers disabled."
# }

# Check status
status = mcp_get_private_mode_status()
print(json.dumps(json.loads(status), indent=2))
# Output:
# {
#   "private_mode": true,
#   "server_count": 0,
#   "servers": []
# }

# Disable private mode
result = mcp_disable_private_mode()
print(json.dumps(json.loads(result), indent=2))
# Output:
# {
#   "private_mode": false,
#   "enabled_servers": 8,
#   "active_servers": ["memory", "sequential-thinking", "fetch", "deepwiki", ...],
#   "message": "Private mode disabled. 8 public MCP servers enabled."
# }
```

### Method 3: Configuration API

Use the config module directly:

```python
from rev.config import set_private_mode, get_private_mode

# Enable private mode
set_private_mode(True)
print(f"Private mode: {get_private_mode()}")  # True

# Disable private mode
set_private_mode(False)
print(f"Private mode: {get_private_mode()}")  # False
```

## What Gets Disabled

### Disabled in Private Mode

**Local NPM MCP Servers:**
- ❌ Memory Server (persistent context)
- ❌ Sequential Thinking Server (reasoning)
- ❌ Fetch Server (HTTP requests)

**Remote MCP Servers:**
- ❌ DeepWiki (GitHub repo RAG)
- ❌ Exa Search (code/doc search)
- ❌ Semgrep (static analysis)
- ❌ Cloudflare Docs (documentation)
- ❌ LLM Text (text analysis)

### Still Available in Private Mode

**User-Configured Servers (with API keys):**
- ✅ GitHub Server (if GITHUB_TOKEN set)
- ✅ Brave Search (if BRAVE_API_KEY set)
- ✅ Any custom servers you've added

These remain available because they require explicit user configuration and trust.

## Architecture

### Configuration Flags

**Environment Variable:**
```bash
REV_PRIVATE_MODE=true|false  # Default: false
```

**Runtime Override:**
```python
from rev.config import set_private_mode
set_private_mode(True)  # Overrides environment variable
```

### Server Classification

Each MCP server configuration includes a `"public"` flag:

```python
# config.py
DEFAULT_MCP_SERVERS = {
    "memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "public": True  # ← Disabled in private mode
    }
}

OPTIONAL_MCP_SERVERS = {
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "public": False  # ← NOT disabled in private mode
    }
}
```

### Server Loading Logic

```python
# MCP client checks private mode before loading
from rev.config import is_mcp_server_allowed

for name, config in DEFAULT_MCP_SERVERS.items():
    if is_mcp_server_allowed(config):  # False for public servers in private mode
        load_server(name, config)
```

## Security Considerations

### What Private Mode Protects

✅ **Code confidentiality**: Prevents code snippets from being sent to external services
✅ **Data privacy**: Keeps sensitive data local
✅ **Network isolation**: Reduces external dependencies
✅ **Compliance**: Helps meet security policies

### What Private Mode Does NOT Protect

⚠️ **API keys in code**: Private mode doesn't prevent accidental credential exposure
⚠️ **Local file access**: Rev still has access to local files
⚠️ **User-configured servers**: Servers with API keys remain active
⚠️ **LLM communication**: Rev still communicates with Ollama (local or remote)

### Best Practices

1. **Enable by default for sensitive projects**: Add `REV_PRIVATE_MODE=true` to project `.env`
2. **Audit server list**: Check `mcp_get_private_mode_status()` to see active servers
3. **Use with Ollama local**: Combine with local Ollama for complete offline operation
4. **Review logs**: Check for any unexpected network requests
5. **Test before production**: Verify all needed functionality works in private mode

## Examples

### Example 1: Secure Project Setup

```bash
# Project .env file
REV_PRIVATE_MODE=true
OLLAMA_BASE_URL=http://localhost:11434  # Local Ollama
OLLAMA_MODEL=gpt-oss:120b-cloud

# Start rev
python -m rev --repl
```

All public MCP servers disabled. Only local Ollama used.

### Example 2: Toggle for Specific Tasks

```python
from rev.mcp import mcp_enable_private_mode, mcp_disable_private_mode

# Enable private mode for sensitive work
mcp_enable_private_mode()

# ... work on confidential code ...

# Disable private mode for documentation lookup
mcp_disable_private_mode()

# ... use DeepWiki, Cloudflare Docs, etc. ...
```

### Example 3: Check Status Before Proceeding

```python
from rev.mcp import mcp_get_private_mode_status
import json

status = json.loads(mcp_get_private_mode_status())

if status["private_mode"]:
    print("✅ Private mode enabled - safe for confidential work")
    print(f"Active servers: {status['server_count']}")
else:
    print("⚠️ Private mode disabled - public servers active")
    print(f"Active servers: {', '.join(status['servers'])}")
```

## Troubleshooting

### Private mode not working

**Check environment variable:**
```bash
echo $REV_PRIVATE_MODE  # Should be "true"
```

**Check runtime status:**
```python
from rev.config import get_private_mode
print(get_private_mode())  # Should be True
```

### Servers still active in private mode

Some servers remain active because they're not marked as public:
- User-configured servers with API keys
- Custom servers added manually

**Check server details:**
```python
from rev.mcp.client import mcp_client

for name, info in mcp_client.servers.items():
    print(f"{name}: {info}")
```

### Need to disable specific servers

Disable individual servers via environment variables:
```bash
# Disable specific servers even outside private mode
export REV_MCP_MEMORY=false
export REV_MCP_DEEPWIKI=false
export REV_MCP_EXA_SEARCH=false
```

## Related Documentation

- [MCP Servers](./MCP_SERVERS.md) - Full list of available MCP servers
- [Default MCP Servers](./DEFAULT_MCP_SERVERS.md) - Default server configuration
- [Configuration Guide](./CONFIGURATION.md) - Environment variables and settings

---

**Last Updated**: 2025-12-09
**Rev Version**: 2.0.1+
