# Rev VSCode Extension

Integrate Rev autonomous AI development system with Visual Studio Code.

## Features

- **Code Analysis**: Analyze code for potential issues and improvements
- **Test Generation**: Automatically generate comprehensive tests
- **Code Refactoring**: Improve code quality and maintainability
- **Debugging**: Fix bugs and errors automatically
- **Documentation**: Add comprehensive documentation to code
- **Custom Tasks**: Execute any Rev task from VSCode

## Installation

1. Install the extension from VSCode Marketplace or manually:
   ```bash
   cd ide-extensions/vscode
   npm install
   code --install-extension rev-vscode-0.1.0.vsix
   ```

2. Install Rev dependencies:
   ```bash
   pip install pygls aiohttp requests
   ```

## Usage

### Quick Start

1. Start the Rev API server:
   - Open Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`)
   - Run `Rev: Start API Server`

2. Use Rev commands:
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
| `Rev: Start LSP Server` | Start LSP server (optional) | - |
| `Rev: Start API Server` | Start API server | - |

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

If auto-start is disabled, start servers manually:

**API Server:**
```bash
python -m rev.ide.api_server
```

**LSP Server (optional):**
```bash
python -m rev.ide.lsp_server
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
- Rev installed (`pip install -e .` from Rev directory)
- Optional: `pygls` for LSP support
- Optional: `aiohttp` for API server

## Troubleshooting

### API Server Not Responding
- Check if Rev API server is running
- Verify `rev.apiUrl` in settings
- Check Rev output panel for errors

### LSP Not Working
- Ensure `pygls` is installed: `pip install pygls`
- Start LSP server manually: `python -m rev.ide.lsp_server`
- Check `rev.lspHost` and `rev.lspPort` settings

### Commands Not Appearing
- Reload VSCode window
- Check extension is activated
- Verify Python path in settings

## Support

For issues and feature requests, visit:
https://github.com/yourusername/rev/issues

## License

MIT License
