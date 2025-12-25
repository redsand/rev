# Rev VSCode Extension

Integrate Rev autonomous AI development system with Visual Studio Code.

## Features

- **Code Analysis**: Analyze code for potential issues and improvements
- **Test Generation**: Automatically generate comprehensive tests
- **Code Refactoring**: Improve code quality and maintainability
- **Debugging**: Fix bugs and errors automatically
- **Documentation**: Add comprehensive documentation to code
- **Model Selection**: Choose from available AI models (Ollama, GPT-4, Claude, etc.)
- **Custom Tasks**: Execute any Rev task from VSCode

## Installation

1. **Install Rev:**
   ```bash
   pip install rev-agentic
   ```

2. **Install VSCode Extension:**
   ```bash
   cd ide-extensions/vscode
   npm install
   code --install-extension rev-vscode-*.vsix
   ```

   Or install from VSCode Marketplace (when published)

## Usage

### Quick Start

1. **Start the Rev API server:**
   ```bash
   rev --ide-api
   ```

2. **Use Rev commands:**
   - Right-click in editor → Select Rev command
   - Use Command Palette → Search for "Rev:"
   - Use keyboard shortcuts (see below)

### Available Commands

| Command | Description | Shortcut |
|---------|-------------|----------|
| `Rev: Analyze Code` | Analyze current file | `Ctrl+Alt+A` / `Cmd+Alt+A` |
| `Rev: Generate Tests` | Generate tests for current file | `Ctrl+Alt+T` / `Cmd+Alt+T` |
| `Rev: Refactor Code` | Refactor selected code or file | `Ctrl+Alt+R` / `Cmd+Alt+R` |
| `Rev: Debug Code` | Debug and fix issues | - |
| `Rev: Add Documentation` | Add documentation | - |
| `Rev: Execute Custom Task` | Execute any Rev task | - |
| `Rev: Select Model` | Choose AI model | - |
| `Rev: Show Current Model` | View active model | - |

### Context Menu

Right-click in editor to access:
- Analyze Code
- Generate Tests
- Refactor Code (when text selected)
- Add Documentation (when text selected)
- Debug Code

### Configuration

Configure Rev in VSCode settings:

```json
{
  "rev.apiUrl": "http://127.0.0.1:8765",
  "rev.lspHost": "127.0.0.1",
  "rev.lspPort": 2087,
  "rev.timeout": 300,
  "rev.enableLSP": true,
  "rev.autoStartServers": false,
  "rev.pythonPath": "python"
}
```

### Manual Server Start

Start the Rev API server in a terminal:

```bash
# Start API server (default: http://127.0.0.1:8765)
rev --ide-api

# Or with custom port
rev --ide-api --ide-api-port 9000
```

## Examples

### Analyze Code
1. Open a Python/JavaScript file
2. Press `Ctrl+Alt+A` (or `Cmd+Alt+A` on Mac)
3. View results in Rev output panel

### Generate Tests
1. Open a source file
2. Press `Ctrl+Alt+T`
3. Rev generates comprehensive tests

### Refactor Code
1. Select code to refactor
2. Press `Ctrl+Alt+R`
3. Rev improves the code

### Execute Custom Task
1. Press `Ctrl+Shift+P`
2. Type `Rev: Execute Custom Task`
3. Enter task description (e.g., "Add error handling to all API endpoints")

## Requirements

- VSCode 1.75.0 or higher
- Python 3.8+
- Rev installed: `pip install rev-agentic`

## Troubleshooting

### API Server Not Responding
- Start Rev API server: `rev --ide-api`
- Verify `rev.apiUrl` in settings (default: http://127.0.0.1:8765)
- Check Rev output panel for errors
- Ensure Rev is installed: `pip install rev-agentic`

### Commands Not Appearing
- Reload VSCode window
- Check extension is activated
- Verify Python path in settings

## Support

For issues and feature requests, visit:
https://github.com/redsand/rev/issues

Documentation: https://github.com/redsand/rev/blob/main/docs/IDE_INTEGRATION.md

## License

MIT License
