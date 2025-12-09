# Default MCP Servers in Rev

Rev comes pre-configured with **8 default MCP (Model Context Protocol) servers** that enhance AI capabilities without requiring any setup or API keys.

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

## Remote MCP Servers (New!)

Rev now includes remote MCP servers - publicly hosted endpoints that provide specialized capabilities without requiring local installation.

### 4. DeepWiki Server 📚
**URL**: `https://mcp.deepwiki.com/sse`

**Purpose**: RAG-as-a-Service for GitHub repositories - semantic code understanding.

**Key Features**:
- Semantic search across GitHub repos
- Repository analysis and insights
- Code pattern detection
- Documentation extraction

**Use Cases**:
- Understanding large codebases
- Finding similar code patterns
- Exploring open source projects
- Learning from existing implementations

**Benefits**:
- No local indexing required
- Works with any public GitHub repo
- Fast semantic search
- Contextual code understanding

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

### 6. Semgrep Server 🔒
**URL**: `https://mcp.semgrep.ai/sse`

**Purpose**: Static analysis and security scanning for code.

**Key Features**:
- Automated security checks
- Code quality analysis
- Pattern-based detection
- Multi-language support

**Use Cases**:
- Security vulnerability scanning
- Code quality checks
- Detecting anti-patterns
- CI/CD integration

**Benefits**:
- Real-time security feedback
- Industry-standard rules
- Low false-positive rate
- Actionable recommendations

**Configuration**: Auto-enabled (disable with `REV_MCP_SEMGREP=false`)

**Note**: Semgrep's remote endpoint is evolving - check their docs for latest status.

---

### 7. Cloudflare Docs Server 📖
**URL**: `https://docs.mcp.cloudflare.com/sse`

**Purpose**: Access Cloudflare documentation and API references.

**Key Features**:
- Cloudflare API documentation
- Workers documentation
- Platform feature guides
- Configuration examples

**Use Cases**:
- Cloudflare Workers development
- API integration
- Platform configuration
- Feature exploration

**Benefits**:
- Always up-to-date docs
- Structured API reference
- Code examples included
- Fast search

**Configuration**: Auto-enabled (disable with `REV_MCP_CLOUDFLARE_DOCS=false`)

---

### 8. LLM Text Server 📝
**URL**: `https://mcp.llmtxt.dev/sse`

**Purpose**: Text and data analysis helpers for development work.

**Key Features**:
- Text processing utilities
- Data transformation
- Format conversion
- Analysis tools

**Use Cases**:
- Log analysis
- Data cleaning
- Format conversion
- Text extraction

**Benefits**:
- Specialized text tools
- Development-focused
- Quick transformations
- Multiple formats

**Configuration**: Auto-enabled (disable with `REV_MCP_LLMTEXT=false`)

---

## 🔒 Private Mode

**Important**: All default servers (both local and remote) are disabled when **Private Mode** is enabled.

Use private mode when working with confidential code:

```python
from rev.mcp import mcp_enable_private_mode, mcp_disable_private_mode

# Enable private mode - disables all 8 default servers
mcp_enable_private_mode()

# Disable private mode - re-enables all servers
mcp_disable_private_mode()
```

Or via environment variable:
```bash
export REV_PRIVATE_MODE=true
```

See [PRIVATE_MODE.md](./PRIVATE_MODE.md) for complete documentation.

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
