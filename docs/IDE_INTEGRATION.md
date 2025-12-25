# IDE Integration Guide

Rev provides comprehensive IDE integration through multiple interfaces, allowing you to use Rev's autonomous AI development capabilities directly from your favorite IDE.

## Table of Contents

- [Overview](#overview)
- [Supported IDEs](#supported-ides)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)

## Overview

Rev IDE integration enables you to:

- **Analyze code** for potential issues and improvements
- **Generate comprehensive tests** automatically
- **Refactor code** to improve quality and maintainability
- **Debug and fix issues** with AI assistance
- **Add documentation** to your code
- **Execute custom Rev tasks** from within your IDE

## Supported IDEs

### Tier 1 Support (Official Extensions)
- **Visual Studio Code** - via LSP and dedicated extension
- **Visual Studio 2022** - via dedicated extension

### Tier 2 Support (LSP Compatible)
- **Sublime Text** - via LSP plugin
- **Atom** - via atom-languageclient
- **Vim/Neovim** - via vim-lsp or coc.nvim
- **Emacs** - via lsp-mode
- **JetBrains IDEs** (IntelliJ, PyCharm, etc.) - via LSP plugin

### Tier 3 Support (API Integration)
- Any IDE with HTTP/REST API support
- Any IDE that can execute Python scripts

## Architecture

Rev IDE integration uses a multi-layered architecture:

```
┌─────────────────────────────────────────────┐
│              IDE Layer                       │
│  (VSCode, Visual Studio, Vim, etc.)         │
└─────────────┬───────────────────────────────┘
              │
              ├──────────────┬─────────────────┐
              │              │                 │
┌─────────────▼─────┐  ┌────▼─────┐  ┌────────▼────────┐
│   LSP Protocol     │  │ HTTP API │  │   CLI Wrapper   │
│   (Universal)      │  │ JSON-RPC │  │   (Direct)      │
└─────────────┬──────┘  └────┬─────┘  └────────┬────────┘
              │              │                 │
              └──────────────┴─────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │     Rev Core System         │
              │   (Orchestrator, Agents)    │
              └─────────────────────────────┘
```

### Integration Methods

1. **Language Server Protocol (LSP)**
   - Universal IDE support
   - Standard protocol
   - Real-time code actions
   - File: `rev/ide/lsp_server.py`

2. **HTTP/JSON-RPC API**
   - RESTful endpoints
   - WebSocket support for real-time updates
   - Remote integration
   - File: `rev/ide/api_server.py`

3. **Client Library**
   - Python client for easy integration
   - Used by IDE plugins
   - File: `rev/ide/client.py`

## Quick Start

### 1. Install Rev

```bash
# Install Rev with all features
pip install rev-agentic
```

That's it! All IDE integration features are included.

### 2. Start IDE Servers

**Start API Server (HTTP/WebSocket):**
```bash
rev --ide-api
```

**Start LSP Server (for universal IDE support):**
```bash
rev --ide-lsp
```

**Or use stdio mode for LSP (direct IDE integration):**
```bash
rev --ide-lsp --ide-lsp-stdio
```

**Custom host/port:**
```bash
# API server on custom port
rev --ide-api --ide-api-port 9000

# LSP server on custom host
rev --ide-lsp --ide-lsp-host 0.0.0.0 --ide-lsp-port 3000
```

### 3. Install IDE Extension

**VSCode:**
```bash
cd ide-extensions/vscode
npm install
code --install-extension rev-vscode-0.1.0.vsix
```

**Visual Studio:**
- Double-click `RevExtension.vsix` to install

## Installation

### Prerequisites

```bash
# Install Rev with all IDE features included
pip install rev-agentic
```

### VSCode Extension

1. **Install from VSIX:**
   ```bash
   cd ide-extensions/vscode
   npm install
   code --install-extension rev-vscode-*.vsix
   ```

2. **Install from Marketplace** (when published):
   - Open VSCode
   - Go to Extensions (Ctrl+Shift+X)
   - Search for "Rev"
   - Click Install

3. **Start Rev API Server:**
   ```bash
   rev --ide-api
   ```

4. **Configure settings** (Ctrl+,):
   ```json
   {
     "rev.apiUrl": "http://127.0.0.1:8765",
     "rev.provider": "ollama",
     "rev.defaultModel": "qwen2.5-coder:32b"
   }
   ```

### Visual Studio Extension

1. **Install from VSIX:**
   - Download `RevExtension.vsix`
   - Double-click to install
   - Restart Visual Studio

2. **Start Rev API Server:**
   ```bash
   rev --ide-api
   ```

3. **Configure** (Tools → Options → Rev):
   - Set API URL (default: http://127.0.0.1:8765)
   - Configure timeout
   - Set default model

### LSP-Compatible IDEs

#### Vim/Neovim with vim-lsp

**Start Rev LSP Server:**
```bash
# In a separate terminal
rev --ide-lsp --ide-lsp-stdio
```

**Configure vim-lsp:**
```vim
" Add to .vimrc or init.vim
if executable('rev')
  au User lsp_setup call lsp#register_server({
    \ 'name': 'rev-lsp',
    \ 'cmd': {server_info->['rev', '--ide-lsp', '--ide-lsp-stdio']},
    \ 'allowlist': ['python', 'javascript', 'typescript'],
    \ })
endif
```

#### Emacs with lsp-mode

```elisp
;; Add to .emacs or init.el
(require 'lsp-mode)
(add-to-list 'lsp-language-id-configuration '(python-mode . "python"))
(lsp-register-client
 (make-lsp-client :new-connection (lsp-stdio-connection
                                   '("rev" "--ide-lsp" "--ide-lsp-stdio"))
                  :major-modes '(python-mode)
                  :server-id 'rev-lsp))
```

#### Sublime Text with LSP

```json
// Add to LSP settings
{
  "clients": {
    "rev-lsp": {
      "enabled": true,
      "command": ["rev", "--ide-lsp", "--ide-lsp-stdio"],
      "selector": "source.python | source.js | source.ts"
    }
  }
}
```

## Configuration

### Starting IDE Servers

**API Server (HTTP/WebSocket):**
```bash
# Default (localhost:8765)
rev --ide-api

# Custom host/port
rev --ide-api --ide-api-host 0.0.0.0 --ide-api-port 9000
```

**LSP Server:**
```bash
# TCP mode (default localhost:2087)
rev --ide-lsp

# Custom host/port
rev --ide-lsp --ide-lsp-host 0.0.0.0 --ide-lsp-port 3000

# Stdio mode (for direct IDE integration)
rev --ide-lsp --ide-lsp-stdio
```

### Programmatic Configuration

```python
# For advanced use cases, you can still use the Python API
from rev.ide import RevAPIServer, RevLSPServer
from rev.config import Config

# Custom configuration
config = Config()
api_server = RevAPIServer(config=config)
api_server.start(host='0.0.0.0', port=9000)
```

### Client Configuration

```python
from rev.ide import RevIDEClient

# Create client
client = RevIDEClient(
    api_url='http://127.0.0.1:8765',
    timeout=300
)

# Use client
result = client.analyze_code('/path/to/file.py')
print(result)
```

## Usage

### VSCode Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| `Rev: Analyze Code` | Ctrl+Alt+A | Analyze current file |
| `Rev: Generate Tests` | Ctrl+Alt+T | Generate tests |
| `Rev: Refactor Code` | Ctrl+Alt+R | Refactor code |
| `Rev: Debug Code` | - | Debug and fix issues |
| `Rev: Add Documentation` | - | Add documentation |
| `Rev: Execute Task` | - | Execute custom task |

### Visual Studio Commands

Access via **Tools → Rev** menu:
- Analyze Code
- Generate Tests
- Refactor Code
- Debug Code
- Add Documentation
- Execute Task

### Programmatic Usage

```python
from rev.ide import RevIDEClient

client = RevIDEClient()

# Analyze code
result = client.analyze_code('/path/to/file.py')
print(f"Analysis: {result}")

# Generate tests
result = client.generate_tests('/path/to/file.py')
print(f"Tests: {result}")

# Refactor code
result = client.refactor_code(
    file_path='/path/to/file.py',
    start_line=10,
    end_line=20
)
print(f"Refactored: {result}")

# Debug code
result = client.debug_code(
    file_path='/path/to/file.py',
    error_message='AttributeError: object has no attribute'
)
print(f"Debug: {result}")

# Add documentation
result = client.add_documentation('/path/to/file.py')
print(f"Documented: {result}")

# Custom task
result = client.execute('Add error handling to all API endpoints')
print(f"Task: {result}")
```

## API Reference

### HTTP REST API

#### Endpoints

**POST /api/v1/execute**
```json
{
  "task": "Add error handling to all API endpoints",
  "task_id": "optional-task-id"
}
```

**POST /api/v1/analyze**
```json
{
  "file_path": "/path/to/file.py"
}
```

**POST /api/v1/test**
```json
{
  "file_path": "/path/to/file.py"
}
```

**POST /api/v1/refactor**
```json
{
  "file_path": "/path/to/file.py",
  "start_line": 10,
  "end_line": 20
}
```

**POST /api/v1/debug**
```json
{
  "file_path": "/path/to/file.py",
  "error_message": "Optional error message"
}
```

**POST /api/v1/document**
```json
{
  "file_path": "/path/to/file.py",
  "start_line": 10,
  "end_line": 20
}
```

**GET /api/v1/status/{task_id}**
- Returns status of a task

**GET /api/v1/tasks**
- Returns list of all tasks

**DELETE /api/v1/task/{task_id}**
- Cancels a task

#### WebSocket

**WS /ws**
- Real-time updates for task progress
- Receives task completion/failure notifications

#### JSON-RPC

**POST /rpc**
```json
{
  "jsonrpc": "2.0",
  "method": "execute",
  "params": {
    "task": "Analyze code"
  },
  "id": 1
}
```

**Available methods:**
- `execute` - Execute task
- `analyze` - Analyze code
- `test` - Generate tests
- `refactor` - Refactor code
- `debug` - Debug code
- `document` - Add documentation
- `status` - Get task status
- `listTasks` - List all tasks
- `cancelTask` - Cancel task

### LSP Protocol

Rev LSP server supports:

**Code Actions:**
- Analyze Code
- Generate Tests
- Refactor Code
- Fix Issues
- Add Documentation

**Commands:**
- `rev.analyzeCode`
- `rev.generateTests`
- `rev.refactorCode`
- `rev.fixIssues`
- `rev.addDocumentation`

**Text Document Sync:**
- Document open/change/save notifications
- Incremental sync

### Python Client API

```python
from rev.ide import RevIDEClient

client = RevIDEClient(api_url='http://127.0.0.1:8765', timeout=300)

# Methods
client.execute(task: str, task_id: Optional[str] = None) -> Dict
client.analyze_code(file_path: str) -> Dict
client.generate_tests(file_path: str) -> Dict
client.refactor_code(file_path: str, start_line: int = None, end_line: int = None) -> Dict
client.debug_code(file_path: str, error_message: str = None) -> Dict
client.add_documentation(file_path: str, start_line: int = None, end_line: int = None) -> Dict
client.get_task_status(task_id: str) -> Dict
client.list_tasks() -> Dict
client.cancel_task(task_id: str) -> Dict
client.jsonrpc_call(method: str, params: Dict = None, request_id: str = None) -> Dict
```

## Troubleshooting

### Common Issues

#### 1. API Server Not Responding

**Problem:** IDE extension shows "Rev API server is not responding"

**Solutions:**
- Check if API server is running: `ps aux | grep "rev --ide-api"`
- Start API server: `rev --ide-api`
- Verify API URL in IDE settings matches server (default: `http://127.0.0.1:8765`)
- Check firewall settings
- Try accessing API directly: `curl http://127.0.0.1:8765/api/v1/tasks`

#### 2. LSP Server Connection Failed

**Problem:** LSP features not working in IDE

**Solutions:**
- Ensure Rev is installed: `pip install rev-agentic`
- Start LSP server: `rev --ide-lsp`
- Check LSP settings in IDE
- Verify port 2087 is not in use
- Check IDE LSP client configuration

#### 3. Commands Not Appearing

**Problem:** Rev commands don't appear in IDE

**Solutions:**
- Reload/restart IDE
- Check extension is installed and enabled
- Verify extension activation events
- Check IDE extension logs

#### 4. Slow Response Times

**Problem:** Rev takes too long to respond

**Solutions:**
- Increase timeout in settings (default: 300s)
- Check system resources (CPU, memory)
- Optimize Rev configuration
- Use faster LLM model
- Enable caching in Rev

#### 5. Python Path Not Found

**Problem:** Extension can't find Python

**Solutions:**
- Set correct Python path in IDE settings
- Add Python to system PATH
- Use absolute path to Python executable
- Verify Python version (3.8+)

### Debugging

#### Enable Debug Logging

**API Server:**
```bash
# Enable Rev debug mode
rev --ide-api --debug
```

**LSP Server:**
```bash
# Enable Rev debug mode
rev --ide-lsp --debug
```

**VSCode Extension:**
1. Open VSCode
2. View → Output → Rev
3. Check for errors

**Visual Studio Extension:**
1. Tools → Options → Debugging → Output Window
2. Set "Extension" to "Verbose"
3. View → Output → Rev

#### Check Server Status

```bash
# Check API server
curl http://127.0.0.1:8765/api/v1/tasks

# Check LSP server (TCP mode)
telnet 127.0.0.1 2087
```

#### Test Client Directly

```python
from rev.ide import RevIDEClient

client = RevIDEClient()
try:
    result = client.list_tasks()
    print("Server is working:", result)
except Exception as e:
    print("Server error:", e)
```

## Advanced Usage

### Custom Server Configuration

```python
from rev.ide import RevAPIServer
from rev.config import Config

# Create custom config
config = Config()
config.llm_provider = 'openai'  # Use OpenAI instead of Ollama
config.model_name = 'gpt-4'

# Start server with custom config
server = RevAPIServer(config=config)
server.start(host='0.0.0.0', port=8765)
```

### Remote IDE Integration

For remote development, expose Rev API server:

```bash
# Start on all interfaces
rev --ide-api --ide-api-host 0.0.0.0 --ide-api-port 8765

# Configure IDE to use remote URL
# In IDE settings: "rev.apiUrl": "http://remote-host:8765"
```

**Security Note:** Use authentication and HTTPS for production deployments.

### Multiple Project Support

```python
from rev.ide import RevAPIServer
from pathlib import Path

# Create server with specific project root
server = RevAPIServer()
server.config.project_root = Path('/path/to/project')
server.start()
```

### WebSocket Real-Time Updates

```javascript
// Connect to WebSocket for real-time updates
const ws = new WebSocket('ws://127.0.0.1:8765/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'task_completed') {
    console.log('Task completed:', data.task_id);
  } else if (data.type === 'task_failed') {
    console.error('Task failed:', data.task_id, data.error);
  }
};

// Send task
fetch('http://127.0.0.1:8765/api/v1/execute', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({task: 'Analyze code'})
});
```

## Performance Optimization

### 1. Enable Caching

Rev automatically caches responses. To optimize:

```python
# In your Rev config
config.enable_cache = True
config.cache_ttl = 3600  # 1 hour
```

### 2. Use Parallel Execution

```python
# Execute multiple tasks in parallel
tasks = [
    client.analyze_code('file1.py'),
    client.analyze_code('file2.py'),
    client.analyze_code('file3.py'),
]
```

### 3. Optimize Timeout

```python
# Adjust timeout based on task complexity
client = RevIDEClient(timeout=600)  # 10 minutes for complex tasks
```

## Security Considerations

### Authentication

For production deployments, add authentication:

```python
# Example: Add API key authentication
from aiohttp import web

async def auth_middleware(app, handler):
    async def middleware(request):
        api_key = request.headers.get('X-API-Key')
        if api_key != 'your-secret-key':
            return web.json_response({'error': 'Unauthorized'}, status=401)
        return await handler(request)
    return middleware

app.middlewares.append(auth_middleware)
```

### HTTPS

For remote access, use HTTPS:

```python
import ssl

ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
ssl_context.load_cert_chain('cert.pem', 'key.pem')

web.run_app(app, host='0.0.0.0', port=8765, ssl_context=ssl_context)
```

## Contributing

To add support for a new IDE:

1. Create extension directory: `ide-extensions/your-ide/`
2. Implement using LSP or HTTP API
3. Add documentation
4. Submit pull request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for details.

## Support

- GitHub Issues: https://github.com/redsand/rev/issues
- Documentation: https://github.com/redsand/rev/blob/main/docs
- Repository: https://github.com/redsand/rev
