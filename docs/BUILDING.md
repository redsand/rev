# Build System Documentation

This document explains how to use the build scripts for the rev.py project.

## Overview

The rev.py project provides multiple ways to set up and build the environment:

1. **Shell Script** (`build.sh`) - For Unix-based systems (Linux, macOS)
2. **PowerShell Script** (`build.ps1`) - For Windows systems
3. **Batch Wrapper** (`build.bat`) - Windows wrapper for the PowerShell script
4. **Makefile** - Alternative build system for Unix-based systems

All build scripts automatically:
- Check Python version requirements
- Create and activate a virtual environment
- Install dependencies
- Run tests (optional)
- Validate the build

## Prerequisites

- **Python 3.7 or higher**
- **pip** (Python package installer)
- **git** (for cloning repositories)

## Shell Script Usage (Linux/macOS)

### Basic Setup

```bash
# Make the script executable
chmod +x build.sh

# Run basic setup
./build.sh
```

### Development Setup with Tests

```bash
# Development setup with tests
./build.sh --dev --test
```

### Full Setup with Coverage

```bash
# Full setup with coverage report
./build.sh --full --coverage
```

### Cleaning Build Artifacts

```bash
# Clean build artifacts
./build.sh --clean

# Clean everything including virtual environment
./build.sh --clean-venv
```

### Help

```bash
# Show help
./build.sh --help
```

## PowerShell Script Usage (Windows)

### Basic Setup

```powershell
# Run basic setup
.\build.ps1
```

### Development Setup with Tests

```powershell
# Development setup with tests
.\build.ps1 -Dev -Test
```

### Full Setup with Coverage

```powershell
# Full setup with coverage report
.\build.ps1 -Full -Coverage
```

### Cleaning Build Artifacts

```powershell
# Clean build artifacts
.\build.ps1 -Clean

# Clean everything including virtual environment
.\build.ps1 -CleanVenv
```

### Help

```powershell
# Show help
.\build.ps1 -Help
```

## Batch File Wrapper (Windows)

For Windows users who prefer a simple double-click approach:

```cmd
# Run basic setup
build.bat

# Pass arguments to the PowerShell script
build.bat --dev --test
```

## Makefile Usage (Linux/macOS)

### Basic Setup

```bash
# Basic setup
make setup

# Development setup
make dev

# Full setup
make full
```

### Running Tests

```bash
# Run tests
make test

# Run tests with coverage
make coverage
```

### Cleaning

```bash
# Clean build artifacts
make clean

# Clean everything including virtual environment
make clean-venv
```

### Help and Validation

```bash
# Show help
make help

# Validate build
make validate

# Activate virtual environment shell
make shell
```

## Dependency Installation Options

### Minimal Dependencies (`requirements.txt`)

- `requests>=2.31.0` - For HTTP requests and Ollama API integration
- `paramiko>=3.0.0` (optional) - For SSH remote execution support

### Development Dependencies (`requirements-dev.txt`)

- All minimal dependencies
- `pytest>=9.0.0` - Testing framework
- `pytest-cov>=7.0.0` - Coverage reporting for tests
- `coverage>=7.12.0` - Code coverage measurement

### Full Dependencies (`requirements-full.txt`)

- `openai` - OpenAI API support
- `requests` - HTTP library
- `paramiko` - SSH support
- `pywinrm` - Windows Remote Management
- `playwright` - Browser automation
- `colorama` - Colored terminal output

## Virtual Environment Management

All build scripts automatically create and manage a virtual environment in the `.venv` directory.

### Activating Manually

```bash
# On Linux/macOS
source .venv/bin/activate

# On Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# On Windows (Command Prompt)
.\.venv\Scripts\activate.bat
```

### Deactivating

```bash
deactivate
```

## Testing

The build system can run tests with or without coverage reporting:

### Without Coverage

```bash
# Shell script
./build.sh --test

# Makefile
make test
```

### With Coverage

```bash
# Shell script
./build.sh --coverage

# Makefile
make coverage
```

Coverage reports are generated in:
- Terminal output (summary)
- HTML format in `htmlcov/` directory

## Validation

The build process validates that rev.py is properly set up:

1. Checks that `rev.py` file exists
2. Verifies that the script can execute (shows help)
3. Confirms dependencies are installed correctly

## Troubleshooting

### Python Version Issues

If you encounter Python version errors:

1. Check your Python version: `python --version` or `python3 --version`
2. Install Python 3.7 or higher if needed
3. Update your PATH to point to the correct Python installation

### Virtual Environment Issues

If virtual environment creation fails:

1. Ensure you have `venv` module: `python -m ensurepip`
2. Try creating it manually: `python -m venv .venv`
3. Activate manually and run pip install commands

### Permission Issues (Linux/macOS)

If you get permission errors:

```bash
# Make scripts executable
chmod +x build.sh
chmod +x build.ps1
```

### PowerShell Execution Policy (Windows)

If PowerShell scripts are blocked:

```powershell
# Set execution policy for current user
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## Customization

You can customize the build process by modifying:

1. **Requirements files** - Add or remove dependencies
2. **Build scripts** - Modify installation steps or validation
3. **Makefile** - Change targets or add new ones

## CI/CD Integration

The build scripts are designed to work in CI/CD environments:

```bash
# CI/CD setup
./build.sh --dev --coverage

# Check exit code for success/failure
if [ $? -eq 0 ]; then
    echo "Build successful"
else
    echo "Build failed"
    exit 1
fi
```

## Next Steps

After building:

1. **Activate the virtual environment**
2. **Run rev.py**: `python rev.py --help`
3. **Start using rev.py**: `python rev.py "Your task description"`

For more information, see:
- [README.md](README.md) - Main project documentation
- [COVERAGE.md](COVERAGE.md) - Test coverage details
- [RECOMMENDATIONS.md](RECOMMENDATIONS.md) - Project recommendations