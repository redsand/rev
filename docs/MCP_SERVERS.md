# Model Context Protocol (MCP) Servers

A curated list of publicly available MCP servers for use with rev.py.

## What is MCP?

Model Context Protocol (MCP) is an open protocol that enables AI assistants to securely access external tools, data sources, and services. MCP servers provide tools that can be called by LLMs during task execution.

## Default MCP Servers

**Rev comes pre-configured with the following default MCP servers** (enabled automatically, no setup required):

### 🎯 Included by Default

1. **Memory Server** (`@modelcontextprotocol/server-memory`)
   - **Purpose**: Persistent memory storage for AI context across sessions
   - **Benefits**: Maintains long-term context, knowledge graphs, entity tracking
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_MEMORY=false`)

2. **Sequential Thinking Server** (`@modelcontextprotocol/server-sequential-thinking`)
   - **Purpose**: Enable step-by-step reasoning for complex problem solving
   - **Benefits**: Improves planning and problem-solving capabilities
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_SEQUENTIAL_THINKING=false`)

3. **Fetch Server** (`@modelcontextprotocol/server-fetch`)
   - **Purpose**: Make HTTP requests to access documentation and APIs
   - **Benefits**: Access external documentation, API endpoints, web resources
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_FETCH=false`)

### 🔧 Configuration

Default servers are automatically loaded when rev starts. To disable a default server:

```bash
# Disable specific servers via environment variables
export REV_MCP_MEMORY=false
export REV_MCP_SEQUENTIAL_THINKING=false
export REV_MCP_FETCH=false
```

Or in your `.env` file:
```bash
REV_MCP_MEMORY=false
REV_MCP_SEQUENTIAL_THINKING=false
REV_MCP_FETCH=false
```

### 📋 Checking Active Servers

List all active MCP servers:
```python
from rev.mcp import mcp_list_servers
print(mcp_list_servers())  # Shows default + any custom servers
```

### 🔒 Private Mode

Rev includes a **private mode** feature for working with confidential code. When enabled, all public MCP servers are disabled:

```python
from rev.mcp import mcp_enable_private_mode, mcp_disable_private_mode

# Enable private mode (disables all public servers)
mcp_enable_private_mode()

# Disable private mode (re-enables public servers)
mcp_disable_private_mode()
```

Or set via environment variable:
```bash
export REV_PRIVATE_MODE=true
```

See [PRIVATE_MODE.md](./PRIVATE_MODE.md) for complete documentation.

---

## Remote MCP Servers (New!)

Rev now includes **remote MCP servers** - publicly hosted SSE/HTTP endpoints that provide specialized development capabilities:

### 🎯 Included Remote Servers

1. **DeepWiki** (`https://mcp.deepwiki.com/sse`)
   - **Purpose**: RAG-as-a-Service for GitHub repositories
   - **Category**: Code Understanding
   - **Benefits**: Semantic code search, repository analysis
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_DEEPWIKI=false`)

2. **Exa Search** (`https://mcp.exa.ai/mcp`)
   - **Purpose**: Code, documentation, and web search
   - **Category**: Search
   - **Benefits**: Find code examples, documentation, best practices
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_EXA_SEARCH=false`)

3. **Semgrep** (`https://mcp.semgrep.ai/sse`)
   - **Purpose**: Static analysis and security scanning
   - **Category**: Security
   - **Benefits**: Automated security checks, code quality
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_SEMGREP=false`)

4. **Cloudflare Docs** (`https://docs.mcp.cloudflare.com/sse`)
   - **Purpose**: Cloudflare documentation access
   - **Category**: Documentation
   - **Benefits**: Quick access to Cloudflare API docs
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_CLOUDFLARE_DOCS=false`)

5. **LLM Text** (`https://mcp.llmtxt.dev/sse`)
   - **Purpose**: Text and data analysis helpers
   - **Category**: Analysis
   - **Benefits**: Advanced text processing and analysis
   - **No API key required** ✅
   - **Auto-enabled**: Yes (disable with `REV_MCP_LLMTEXT=false`)

**Note**: All remote servers are disabled when [Private Mode](./PRIVATE_MODE.md) is enabled.

---

## Official MCP Servers

### 1. **Filesystem Server**
**Repository**: `@modelcontextprotocol/server-filesystem`
**Purpose**: Read and write files on the local filesystem
**Use Cases**: File operations, code editing, log analysis

```bash
# Install
npm install -g @modelcontextprotocol/server-filesystem

# Configure in rev.py
mcp_add_server "filesystem" "npx" "-y @modelcontextprotocol/server-filesystem /path/to/allowed/directory"
```

**Tools**:
- `read_file`: Read file contents
- `write_file`: Write to files
- `list_directory`: List directory contents
- `search_files`: Search for files

---

### 2. **GitHub Server**
**Repository**: `@modelcontextprotocol/server-github`
**Purpose**: Interact with GitHub repositories, issues, and PRs
**Use Cases**: Code review, issue management, repository analysis

```bash
# Install
npm install -g @modelcontextprotocol/server-github

# Configure with GitHub token
mcp_add_server "github" "npx" "-y @modelcontextprotocol/server-github"
```

**Tools**:
- `create_issue`: Create GitHub issues
- `list_issues`: List repository issues
- `create_pull_request`: Create PRs
- `get_file_contents`: Read files from repos
- `push_files`: Push changes to repos

**Environment**: Requires `GITHUB_TOKEN` environment variable

---

### 3. **GitLab Server**
**Repository**: `@modelcontextprotocol/server-gitlab`
**Purpose**: Interact with GitLab projects, issues, and merge requests
**Use Cases**: GitLab workflow automation

```bash
npm install -g @modelcontextprotocol/server-gitlab

mcp_add_server "gitlab" "npx" "-y @modelcontextprotocol/server-gitlab"
```

**Environment**: Requires `GITLAB_TOKEN` environment variable

---

### 4. **PostgreSQL Server**
**Repository**: `@modelcontextprotocol/server-postgres`
**Purpose**: Query and analyze PostgreSQL databases
**Use Cases**: Database analysis, data exploration, schema inspection

```bash
npm install -g @modelcontextprotocol/server-postgres

mcp_add_server "postgres" "npx" "-y @modelcontextprotocol/server-postgres postgresql://user:pass@localhost/dbname"
```

**Tools**:
- `query`: Execute SQL queries
- `list_tables`: List database tables
- `describe_table`: Get table schema
- `analyze`: Analyze query performance

---

### 5. **SQLite Server**
**Repository**: `@modelcontextprotocol/server-sqlite`
**Purpose**: Query SQLite databases
**Use Cases**: Local database analysis, embedded database work

```bash
npm install -g @modelcontextprotocol/server-sqlite

mcp_add_server "sqlite" "npx" "-y @modelcontextprotocol/server-sqlite /path/to/database.db"
```

---

### 6. **Brave Search Server**
**Repository**: `@modelcontextprotocol/server-brave-search`
**Purpose**: Web search using Brave Search API
**Use Cases**: Research, fact-checking, current information

```bash
npm install -g @modelcontextprotocol/server-brave-search

mcp_add_server "brave-search" "npx" "-y @modelcontextprotocol/server-brave-search"
```

**Environment**: Requires `BRAVE_API_KEY` from https://brave.com/search/api/

**Tools**:
- `brave_web_search`: Search the web
- `brave_local_search`: Search local businesses

---

### 7. **Google Maps Server**
**Repository**: `@modelcontextprotocol/server-google-maps`
**Purpose**: Geocoding, directions, place searches
**Use Cases**: Location-based services, mapping

```bash
npm install -g @modelcontextprotocol/server-google-maps

mcp_add_server "google-maps" "npx" "-y @modelcontextprotocol/server-google-maps"
```

**Environment**: Requires `GOOGLE_MAPS_API_KEY`

---

### 8. **Slack Server**
**Repository**: `@modelcontextprotocol/server-slack`
**Purpose**: Send messages, manage channels
**Use Cases**: Team notifications, workflow automation

```bash
npm install -g @modelcontextprotocol/server-slack

mcp_add_server "slack" "npx" "-y @modelcontextprotocol/server-slack"
```

**Environment**: Requires `SLACK_BOT_TOKEN`

---

### 9. **Memory Server**
**Repository**: `@modelcontextprotocol/server-memory`
**Purpose**: Persistent memory storage for AI context
**Use Cases**: Long-term context, knowledge graphs, entity tracking

```bash
npm install -g @modelcontextprotocol/server-memory

mcp_add_server "memory" "npx" "-y @modelcontextprotocol/server-memory"
```

**Tools**:
- `create_entities`: Store entities/concepts
- `create_relations`: Link entities
- `search_entities`: Query knowledge graph
- `observe`: Add observations

---

### 10. **Puppeteer Server**
**Repository**: `@modelcontextprotocol/server-puppeteer`
**Purpose**: Browser automation and web scraping
**Use Cases**: Web testing, screenshots, data extraction

```bash
npm install -g @modelcontextprotocol/server-puppeteer

mcp_add_server "puppeteer" "npx" "-y @modelcontextprotocol/server-puppeteer"
```

**Tools**:
- `navigate`: Go to URL
- `screenshot`: Take screenshots
- `click`: Click elements
- `fill`: Fill forms
- `evaluate`: Run JavaScript

---

## Community MCP Servers

### 11. **Fetch Server** (HTTP Requests)
**Repository**: `@modelcontextprotocol/server-fetch`
**Purpose**: Make HTTP requests to APIs
**Use Cases**: API testing, data fetching

```bash
npm install -g @modelcontextprotocol/server-fetch

mcp_add_server "fetch" "npx" "-y @modelcontextprotocol/server-fetch"
```

---

### 12. **AWS KB Retrieval Server**
**Repository**: `@modelcontextprotocol/server-aws-kb-retrieval`
**Purpose**: Retrieve from AWS Knowledge Bases
**Use Cases**: RAG applications, documentation search

```bash
npm install -g @modelcontextprotocol/server-aws-kb-retrieval

mcp_add_server "aws-kb" "npx" "-y @modelcontextprotocol/server-aws-kb-retrieval"
```

**Environment**: Requires AWS credentials

---

### 13. **Sentry Server**
**Repository**: `@modelcontextprotocol/server-sentry`
**Purpose**: Access Sentry error tracking data
**Use Cases**: Error analysis, debugging

```bash
npm install -g @modelcontextprotocol/server-sentry

mcp_add_server "sentry" "npx" "-y @modelcontextprotocol/server-sentry"
```

**Environment**: Requires `SENTRY_AUTH_TOKEN`

---

### 14. **Sequential Thinking Server**
**Repository**: `@modelcontextprotocol/server-sequential-thinking`
**Purpose**: Enable step-by-step reasoning
**Use Cases**: Complex problem solving, planning

```bash
npm install -g @modelcontextprotocol/server-sequential-thinking

mcp_add_server "thinking" "npx" "-y @modelcontextprotocol/server-sequential-thinking"
```

---

### 15. **EverArt Server**
**Repository**: `@modelcontextprotocol/server-everart`
**Purpose**: AI image generation
**Use Cases**: Creating images, visual content

```bash
npm install -g @modelcontextprotocol/server-everart

mcp_add_server "everart" "npx" "-y @modelcontextprotocol/server-everart"
```

**Environment**: Requires `EVERART_API_KEY`

---

## Python-Based MCP Servers

### 16. **FastMCP** (Python Framework)
**Repository**: `fastmcp`
**Purpose**: Build custom MCP servers in Python
**Use Cases**: Custom tool development

```bash
pip install fastmcp

# Create custom server
python my_mcp_server.py
```

**Documentation**: https://github.com/jlowin/fastmcp

---

## Documentation & Knowledge Servers

### 17. **Documentation Server**
**Type**: Custom implementation recommended
**Purpose**: Read and search project documentation
**Use Cases**: API docs, library docs, internal docs

**Recommended Approach**:
```python
# Use Filesystem Server + Brave Search
# Point filesystem to docs directory
# Use search for external docs
```

---

### 18. **Confluence Server** (Community)
**Purpose**: Access Confluence wiki pages
**Use Cases**: Internal documentation, team knowledge

*Note: Check community repositories for implementation*

---

### 19. **Notion Server** (Community)
**Purpose**: Read/write Notion pages
**Use Cases**: Documentation, knowledge management

*Note: Check community repositories for implementation*

---

## Recommended MCP Servers for rev.py

### Essential Servers
1. **Filesystem** - Core file operations
2. **Memory** - Persistent context across sessions
3. **GitHub/GitLab** - Repository management

### Development Servers
4. **PostgreSQL/SQLite** - Database work
5. **Puppeteer** - Browser automation
6. **Fetch** - API testing

### Research Servers
7. **Brave Search** - Web research
8. **AWS KB Retrieval** - Documentation search

### Monitoring Servers
9. **Sentry** - Error tracking
10. **Slack** - Notifications

---

## How to Add MCP Servers to rev.py

### Method 1: Using rev.py CLI
```bash
# Start rev.py
python rev.py

# Add server interactively
> mcp_add_server "github" "npx" "-y @modelcontextprotocol/server-github"
```

### Method 2: Programmatically
```python
from rev.tools.registry import execute_tool

# Add MCP server
result = execute_tool("mcp_add_server", {
    "name": "github",
    "command": "npx",
    "args": "-y @modelcontextprotocol/server-github"
})

# List servers
servers = execute_tool("mcp_list_servers", {})

# Call MCP tool
result = execute_tool("mcp_call_tool", {
    "server": "github",
    "tool": "list_issues",
    "arguments": '{"repo": "owner/repo"}'
})
```

### Method 3: Configuration File
Create `~/.rev/mcp_servers.json`:
```json
{
  "servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"]
    }
  }
}
```

---

## Security Considerations

⚠️ **Important Security Notes**:

1. **Filesystem Server**: Only grant access to specific directories
2. **API Keys**: Use environment variables, never hardcode
3. **Database Servers**: Use read-only credentials when possible
4. **GitHub/GitLab**: Use tokens with minimal required permissions
5. **Network Access**: MCP servers can make network requests

---

## Environment Variables Setup

Create `.env` file in your project:
```bash
# GitHub
GITHUB_TOKEN=ghp_your_token_here

# Brave Search
BRAVE_API_KEY=your_brave_api_key

# Google Maps
GOOGLE_MAPS_API_KEY=your_google_maps_key

# Slack
SLACK_BOT_TOKEN=xoxb-your-slack-token

# Sentry
SENTRY_AUTH_TOKEN=your_sentry_token

# GitLab
GITLAB_TOKEN=your_gitlab_token

# AWS (for AWS KB Retrieval)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
```

Load in rev.py:
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## Troubleshooting

### Server won't start
```bash
# Check npm/node installation
node --version
npm --version

# Install server globally
npm install -g @modelcontextprotocol/server-name

# Check server directly
npx @modelcontextprotocol/server-name
```

### Authentication errors
- Verify environment variables are set
- Check token permissions
- Ensure tokens haven't expired

### Connection issues
- Check network connectivity
- Verify server is running
- Check firewall settings

---

## Creating Custom MCP Servers

### Using FastMCP (Python)
```python
from fastmcp import FastMCP

mcp = FastMCP("my-server")

@mcp.tool()
def analyze_code(code: str) -> dict:
    """Analyze code quality."""
    # Your analysis logic
    return {"quality": "good"}

if __name__ == "__main__":
    mcp.run()
```

### Using MCP SDK (TypeScript)
```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";

const server = new Server({
  name: "my-server",
  version: "1.0.0"
});

server.setRequestHandler(/* ... */);
```

---

## Resources

- **MCP Specification**: https://spec.modelcontextprotocol.io/
- **Official Servers**: https://github.com/modelcontextprotocol/servers
- **FastMCP (Python)**: https://github.com/jlowin/fastmcp
- **MCP SDK**: https://github.com/modelcontextprotocol/sdk
- **Community Servers**: https://github.com/topics/mcp-server

---

## Next Steps

1. Install essential MCP servers
2. Configure authentication (API keys, tokens)
3. Test servers with rev.py
4. Create custom servers for project-specific needs
5. Set up automated MCP server management

---

## Contributing

Found a new MCP server? Submit a PR to add it to this list!

**Required Info**:
- Server name and repository
- Purpose and use cases
- Installation instructions
- Required environment variables
- Example usage
