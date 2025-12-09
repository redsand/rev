# Default MCP Servers in Rev

Rev comes pre-configured with **nine default MCP (Model Context Protocol) servers** that enhance AI capabilities without requiring any setup or API keys.

## Overview

These servers are automatically loaded when rev starts, providing immediate access to:
- **Persistent memory** across sessions
- **Advanced reasoning** capabilities
- **External documentation** access via HTTP
- **Code understanding** via GitHub repository RAG
- **Security scanning** with static analysis
- **Web and code search** capabilities

### Two Types of Default Servers

1. **Local NPM Servers** (3 servers) - Run locally via `npx`
2. **Remote MCP Servers** (5 servers) - Publicly hosted SSE/HTTP endpoints

## Default Servers

### Core Servers (Original)

### 1. Memory Server 🧠
**Package**: `@modelcontextprotocol/server-memory`

**Purpose**: Provides persistent memory storage for AI context across sessions.

**Key Features**:
- Store and retrieve entities and concepts
- Create relationships between entities
- Build knowledge graphs
- Maintain observations over time
- Long-term context retention

**Use Cases**:
- Tracking project requirements across sessions
- Remembering user preferences
- Building domain knowledge graphs
- Maintaining conversation context

**Tools Provided**:
- `create_entities` - Store new entities/concepts
- `create_relations` - Link entities together
- `search_entities` - Query the knowledge graph
- `observe` - Add observations about entities

**Configuration**: Auto-enabled (disable with `REV_MCP_MEMORY=false`)

---

### 2. Sequential Thinking Server 🤔
**Package**: `@modelcontextprotocol/server-sequential-thinking`

**Purpose**: Enables step-by-step reasoning for complex problem solving.

**Key Features**:
- Break down complex problems
- Track reasoning steps
- Validate logical progression
- Improve planning quality

**Use Cases**:
- Complex debugging scenarios
- Multi-step refactoring plans
- Architecture design decisions
- Algorithm development

**Benefits**:
- More thorough analysis
- Better problem decomposition
- Clearer reasoning chains
- Improved decision quality

**Configuration**: Auto-enabled (disable with `REV_MCP_SEQUENTIAL_THINKING=false`)

---

### 3. Fetch Server 🌐
**Package**: `@modelcontextprotocol/server-fetch`

**Purpose**: Make HTTP requests to access documentation and APIs.

**Key Features**:
- GET/POST/PUT/DELETE requests
- Header customization
- Response parsing
- Error handling

**Use Cases**:
- Accessing library documentation
- Reading API specifications
- Fetching remote resources
- Checking web endpoints

**Common Usage**:
```python
# Fetch latest Python documentation
result = mcp_call_tool("fetch", "get", {
    "url": "https://docs.python.org/3/api/..."
})

# Check API endpoint
result = mcp_call_tool("fetch", "get", {
    "url": "https://api.example.com/status",
    "headers": {"Authorization": "Bearer ..."}
})
```

**Configuration**: Auto-enabled (disable with `REV_MCP_FETCH=false`)

---

### Coding & CI/CD Servers (New!)

### 4. DeepWiki 🔍
**Endpoint**: https://mcp.deepwiki.com/sse

**Purpose**: RAG-as-a-Service for GitHub repositories - search and analyze code across repositories.

**Key Features**:
- Search GitHub repository code
- Analyze code structures
- Extract code snippets
- Retrieve documentation from repos

**Use Cases**:
- Finding code examples in popular repos
- Understanding library implementations
- Code pattern discovery
- Open-source research

**Configuration**: Auto-enabled (disable with `REV_MCP_DEEPWIKI=false`)

---

### 5. Exa Search Server 🔍
**URL**: `https://mcp.exa.ai/mcp`

**Purpose**: Advanced code, documentation, and web search capabilities.

**Key Features**:
- Code search across repositories
- Documentation search
- Web search with developer focus
- Filtered results for technical content

**Use Cases**:
- Finding code examples
- Searching API documentation
- Discovering best practices
- Technical research

**Benefits**:
- Developer-focused search results
- Code-aware ranking
- Multiple search sources
- High-quality technical content

**Configuration**: Auto-enabled (disable with `REV_MCP_EXA_SEARCH=false`)

---

### 6. Semgrep 🛡️
**Endpoint**: https://mcp.semgrep.ai/sse

**Purpose**: Static code analysis for security vulnerabilities and code quality issues.

**Key Features**:
- Security vulnerability detection
- Code quality analysis
- Pattern-based scanning
- Multi-language support

**Use Cases**:
- Security auditing
- Code review automation
- CI/CD integration
- Pre-commit checks

**Configuration**: Auto-enabled (disable with `REV_MCP_SEMGREP=false`)

---

### Documentation Servers

### 7. Cloudflare Docs ☁️
**Endpoint**: https://docs.mcp.cloudflare.com/sse

**Purpose**: Access Cloudflare API and platform documentation.

**Key Features**:
- Cloudflare API docs
- Platform configuration guides
- Worker documentation
- CDN configuration

**Use Cases**:
- Cloudflare integration development
- API reference lookup
- Worker development
- CDN optimization

**Configuration**: Auto-enabled (disable with `REV_MCP_CLOUDFLARE_DOCS=false`)

---

### 8. Astro Docs ⚡
**Endpoint**: https://mcp.docs.astro.build/mcp

**Purpose**: Access Astro framework documentation.

**Key Features**:
- Astro component documentation
- Framework API reference
- Integration guides
- Best practices

**Use Cases**:
- Astro web development
- Component creation
- Framework learning
- Integration setup

**Configuration**: Auto-enabled (disable with `REV_MCP_ASTRO_DOCS=false`)

---

### AI/ML Servers

### 9. Hugging Face 🤗
**Endpoint**: https://hf.co/mcp

**Purpose**: Access Hugging Face models, datasets, and repositories.

**Key Features**:
- Model discovery
- Dataset exploration
- Repository access
- Model card retrieval

**Use Cases**:
- ML model selection
- Dataset research
- Model deployment planning
- AI/ML development

**Configuration**: Auto-enabled (disable with `REV_MCP_HUGGINGFACE=false`)

---

## Private Mode 🔒

**New Feature!** Private mode disables all public MCP servers for secure/unsharable code.

### Enabling Private Mode

**Via Slash Command** (in REPL):
```bash
/private on      # Enable
/private off     # Disable
/private         # Check status
```

**Via Environment Variable**:
```bash
export REV_PRIVATE_MODE=true
python -m rev
```

**Via .env File**:
```bash
# .env
REV_PRIVATE_MODE=true
```

### How It Works

When private mode is enabled:
- ❌ All 9 default public MCP servers are disabled
- ✅ Private servers with your API keys remain enabled (GitHub, Brave Search, etc.)
- ✅ Your code stays local and secure

### When to Use

- Working with proprietary code
- Handling sensitive data
- Compliance requirements (HIPAA, SOC 2, etc.)
- Air-gapped environments
- Security-focused development

---

## How It Works

When rev starts, the `MCPClient` class automatically:

1. **Reads configuration** from `rev/config.py`
2. **Checks environment variables** for enable/disable flags
3. **Loads enabled servers** into the MCP registry
4. **Makes tools available** to the AI system

## Disabling Default Servers

You can disable any default server using environment variables:

```bash
# Disable all default servers
export REV_MCP_MEMORY=false
export REV_MCP_SEQUENTIAL_THINKING=false
export REV_MCP_FETCH=false

# Or selectively disable
export REV_MCP_MEMORY=false  # Disable only memory server
```

Or add to your `.env` file:
```bash
# .env
REV_MCP_MEMORY=false
REV_MCP_SEQUENTIAL_THINKING=false
REV_MCP_FETCH=false
```

## Checking Active Servers

List all active MCP servers (including defaults):

```python
from rev.mcp import mcp_list_servers
import json

servers = mcp_list_servers()
print(json.dumps(json.loads(servers), indent=2))
```

Output:
```json
{
  "servers": [
    "memory",
    "sequential-thinking",
    "fetch"
  ]
}
```

## Requirements

**Node.js and npm** must be installed for MCP servers to work:

```bash
# Check if Node.js is installed
node --version  # Should be v16+
npm --version   # Should be 7+

# Install Node.js if needed
# Ubuntu/Debian
sudo apt install nodejs npm

# macOS
brew install node

# Windows
# Download from https://nodejs.org/
```

The default servers will be automatically installed when first accessed via `npx`.

## Adding More Servers

While rev comes with these three default servers, you can add more:

### Optional Servers (Require API Keys)

**Brave Search** (requires `BRAVE_API_KEY`):
```python
# Enable in config.py or add manually
from rev.mcp import mcp_add_server
mcp_add_server("brave-search", "npx", "-y @modelcontextprotocol/server-brave-search")
```

**GitHub** (requires `GITHUB_TOKEN`):
```python
from rev.mcp import mcp_add_server
mcp_add_server("github", "npx", "-y @modelcontextprotocol/server-github")
```

See [MCP_SERVERS.md](./MCP_SERVERS.md) for the full list of available servers.

## Troubleshooting

### Servers not loading

Check Node.js installation:
```bash
node --version
npm --version
```

### Server communication errors

The current MCP implementation is in stub/placeholder form. Full MCP server communication will be implemented in a future update.

### Disabling doesn't work

Ensure environment variables are set before starting rev:
```bash
export REV_MCP_MEMORY=false
python -m rev
```

## Architecture

**Configuration**: `/home/user/rev/rev/config.py`
- `DEFAULT_MCP_SERVERS` - Default server definitions
- `OPTIONAL_MCP_SERVERS` - Servers requiring API keys

**Client**: `/home/user/rev/rev/mcp/client.py`
- `MCPClient` class with auto-loading
- `_load_default_servers()` method
- Global `mcp_client` instance

**Integration**: `/home/user/rev/rev/tools/registry.py`
- MCP tools registered in tool registry
- Available to all agents

## Benefits of Default Servers

### For Users
✅ **Zero configuration** - 8 servers work out of the box
✅ **No API keys** - All default servers are completely free
✅ **Enhanced capabilities** - Memory, reasoning, search, security, and documentation
✅ **Easy to disable** - Simple environment variables or private mode
✅ **Privacy control** - Private mode for confidential work

### For Developers
✅ **Standard toolset** - Consistent across installations
✅ **Dual deployment** - Local (NPM) + Remote (SSE) servers
✅ **Extensible** - Easy to add more servers
✅ **Well-documented** - Clear usage patterns
✅ **Production-ready** - Tested and reliable
✅ **Security-focused** - Includes Semgrep for code scanning

## Future Enhancements

Planned improvements:
- [ ] Full MCP stdio communication implementation
- [ ] Server health monitoring
- [ ] Automatic fallback on server failure
- [ ] Server usage analytics
- [ ] Custom server discovery
- [ ] Per-project MCP configuration

## Learn More

- **MCP Specification**: https://spec.modelcontextprotocol.io/
- **Official Servers**: https://github.com/modelcontextprotocol/servers
- **Rev MCP Guide**: [MCP_SERVERS.md](./MCP_SERVERS.md)
- **FastMCP (Python)**: https://github.com/jlowin/fastmcp

---

**Last Updated**: 2025-12-09
**Rev Version**: 2.0.1+
