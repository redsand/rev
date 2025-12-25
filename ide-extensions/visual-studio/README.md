# Rev Visual Studio Extension

Integrate Rev autonomous AI development system with Visual Studio 2022.

## Features

- **Code Analysis**: Analyze code for potential issues and improvements
- **Test Generation**: Automatically generate comprehensive tests
- **Code Refactoring**: Improve code quality and maintainability
- **Debugging**: Fix bugs and errors automatically
- **Documentation**: Add comprehensive documentation to code
- **Custom Tasks**: Execute any Rev task from Visual Studio

## Requirements

- Visual Studio 2022 (Community, Professional, or Enterprise)
- .NET Framework 4.7.2 or higher
- Python 3.8+ with Rev installed

## Installation

### From VSIX

1. Download the latest `RevExtension.vsix` from releases
2. Double-click the VSIX file to install
3. Restart Visual Studio

### From Source

1. Open `RevExtension.sln` in Visual Studio 2022
2. Build the solution (F6)
3. Press F5 to launch experimental instance
4. The extension will be installed in the experimental instance

## Setup

1. **Install Rev:**
   ```bash
   pip install rev-agentic
   ```

2. **Start the Rev API server:**
   ```bash
   rev --ide-api
   ```

## Usage

### Available Commands

Access Rev commands through:
- **Tools** → **Rev** menu
- **Right-click context menu** in code editor
- **Keyboard shortcuts** (configurable in Tools → Options → Keyboard)

| Command | Description |
|---------|-------------|
| **Rev: Analyze Code** | Analyze current file for issues |
| **Rev: Generate Tests** | Generate comprehensive tests |
| **Rev: Refactor Code** | Refactor selected code or file |
| **Rev: Debug Code** | Debug and fix issues |
| **Rev: Add Documentation** | Add documentation to code |
| **Rev: Execute Task** | Execute custom Rev task |

### Examples

#### Analyze Code
1. Open a C#/Python/JavaScript file
2. Click **Tools** → **Rev** → **Analyze Code**
3. View results in Output window (View → Output → Rev)

#### Generate Tests
1. Open a source file
2. Right-click → **Rev** → **Generate Tests**
3. Rev generates comprehensive tests

#### Refactor Code
1. Select code to refactor
2. Right-click → **Rev** → **Refactor Code**
3. Rev improves the code

#### Execute Custom Task
1. Click **Tools** → **Rev** → **Execute Task**
2. Enter task description
3. View progress in Output window

## Configuration

Configure Rev in **Tools** → **Options** → **Rev**:

- **API URL**: Rev API server URL (default: `http://127.0.0.1:8765`)
- **Timeout**: Request timeout in seconds (default: 300)
- **Python Path**: Path to Python executable
- **Auto Start**: Automatically start Rev servers

## Building from Source

### Prerequisites
- Visual Studio 2022 with Visual Studio extension development workload
- .NET Framework 4.7.2 SDK
- Visual Studio SDK

### Build Steps
1. Clone the repository
2. Open `RevExtension.sln`
3. Restore NuGet packages
4. Build solution (Ctrl+Shift+B)
5. Output VSIX will be in `bin/Debug` or `bin/Release`

### Debug
1. Set `RevExtension` as startup project
2. Press F5
3. Visual Studio experimental instance launches with extension

## Project Structure

```
visual-studio/
├── RevExtension.vsixmanifest    # Extension manifest
├── RevPackage.cs                # Main package class
├── Commands/                    # Command implementations
│   ├── BaseRevCommand.cs        # Base command class
│   ├── AnalyzeCodeCommand.cs    # Analyze code command
│   ├── GenerateTestsCommand.cs  # Generate tests command
│   ├── RefactorCodeCommand.cs   # Refactor command
│   ├── DebugCodeCommand.cs      # Debug command
│   ├── AddDocumentationCommand.cs # Documentation command
│   └── ExecuteTaskCommand.cs    # Custom task command
├── Services/                    # Services and utilities
│   ├── RevApiClient.cs         # API client
│   └── RevOutputPane.cs        # Output window pane
└── Resources/                   # Icons and resources
```

## Troubleshooting

### Extension Not Loading
- Check Visual Studio version (must be 2022)
- Verify extension is enabled in Extensions → Manage Extensions
- Check Output window for errors

### API Server Not Responding
- Start Rev API server: `rev --ide-api`
- Verify API URL in Tools → Options → Rev (default: http://127.0.0.1:8765)
- Check firewall settings
- Ensure Rev is installed: `pip install rev-agentic`

### Commands Not Appearing
- Rebuild extension
- Reset Visual Studio settings
- Check Output window → Extension Manager for errors

### Python Not Found
- Set correct Python path in options
- Ensure Python is in system PATH
- Restart Visual Studio after changing Python path

## Development

### Adding New Commands

1. Create new command class in `Commands/` inheriting from `BaseRevCommand`
2. Implement command logic
3. Register command in `RevPackage.cs`
4. Add menu item in `RevExtension.vsct`

### Testing

1. Write unit tests in `Tests/` project
2. Use Visual Studio experimental instance for integration testing
3. Test with multiple Visual Studio versions

## Support

For issues and feature requests:
- GitHub Issues: https://github.com/yourusername/rev/issues
- Documentation: https://github.com/yourusername/rev/docs

## License

MIT License

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
