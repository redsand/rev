# Build script for rev - Autonomous CI/CD Agent
# This script sets up the environment and runs the build process

param(
    [switch]$Dev,
    [switch]$Full,
    [switch]$Test,
    [switch]$Coverage,
    [switch]$Clean,
    [switch]$CleanVenv,
    [switch]$Help,
    [switch]$Publish
)

# Colors for output
$RED = "Red"
$GREEN = "Green"
$YELLOW = "Yellow"
$BLUE = "Blue"
$WHITE = "White"

# Script information
$SCRIPT_NAME = "rev Build Script"
$SCRIPT_VERSION = "1.1.0"

function Write-Status {
    param([string]$Message)
    Write-Host "✓ " -ForegroundColor $GREEN -NoNewline
    Write-Host $Message -ForegroundColor $WHITE
}

function Write-WarningMsg {
    param([string]$Message)
    Write-Host "! " -ForegroundColor $YELLOW -NoNewline
    Write-Host $Message -ForegroundColor $WHITE
}

function Write-ErrorExit {
    param([string]$Message)
    Write-Host "✗ " -ForegroundColor $RED -NoNewline
    Write-Host $Message -ForegroundColor $WHITE
    exit 1
}

function Write-Header {
    Write-Host "================================" -ForegroundColor $BLUE
    Write-Host "  $SCRIPT_NAME v$SCRIPT_VERSION" -ForegroundColor $BLUE
    Write-Host "================================" -ForegroundColor $BLUE
    Write-Host ""
}

# Function to check if a command exists
function Test-CommandExists {
    param([string]$Command)
    try {
        $null = Get-Command $Command -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# Function to check Python version
function Check-PythonVersion {
    if (Test-CommandExists "python") {
        $PYTHON_CMD = "python"
    }
    elseif (Test-CommandExists "python3") {
        $PYTHON_CMD = "python3"
    }
    else {
        Write-ErrorExit "Python is not installed"
    }

    try {
        $PYTHON_VERSION = & $PYTHON_CMD --version 2>&1
        $VERSION_STRING = $PYTHON_VERSION.ToString().Split(' ')[1]
        Write-Status "Python version: $VERSION_STRING"
        
        $VERSION_PARTS = $VERSION_STRING.Split('.')
        $MAJOR = [int]$VERSION_PARTS[0]
        $MINOR = [int]$VERSION_PARTS[1]
        
        if ($MAJOR -lt 3 -or ($MAJOR -eq 3 -and $MINOR -lt 7)) {
            Write-ErrorExit "Python 3.7 or higher is required. Found Python $VERSION_STRING"
        }
    }
    catch {
        Write-ErrorExit "Failed to check Python version: $($_.Exception.Message)"
    }
}

# Function to check if virtual environment is active
function Test-VenvActive {
    return ![string]::IsNullOrEmpty($env:VIRTUAL_ENV)
}

# Function to create virtual environment
function Create-Venv {
    if (Test-VenvActive) {
        Write-Status "Virtual environment already active: $env:VIRTUAL_ENV"
        return
    }

    $VENV_DIR = ".venv"
    
    if (-not (Test-Path $VENV_DIR)) {
        Write-Status "Creating virtual environment..."
        & python -m venv $VENV_DIR
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorExit "Failed to create virtual environment"
        }
    }

    # Activate virtual environment
    $ACTIVATE_SCRIPT = "$VENV_DIR\Scripts\Activate.ps1"
    if (Test-Path $ACTIVATE_SCRIPT) {
        & $ACTIVATE_SCRIPT
        Write-Status "Virtual environment activated"
    }
    else {
        Write-ErrorExit "Failed to activate virtual environment"
    }
}

# Function to install dependencies
function Install-Dependencies {
    Write-Status "Installing dependencies..."
    
    # Install minimal requirements
    if (Test-Path "requirements.txt") {
        & pip install -r requirements.txt
        if ($LASTEXITCODE -eq 0) {
            Write-Status "Minimal requirements installed"
        }
        else {
            Write-WarningMsg "Failed to install minimal requirements"
        }
    }
    
    # Install development requirements if requested
    if ($Dev) {
        if (Test-Path "requirements-dev.txt") {
            & pip install -r requirements-dev.txt
            if ($LASTEXITCODE -eq 0) {
                Write-Status "Development requirements installed"
            }
            else {
                Write-WarningMsg "Failed to install development requirements"
            }
        }
    }
    
    # Install full requirements if requested
    if ($Full) {
        if (Test-Path "requirements-full.txt") {
            & pip install -r requirements-full.txt
            if ($LASTEXITCODE -eq 0) {
                Write-Status "Full requirements installed"
            }
            else {
                Write-WarningMsg "Failed to install full requirements"
            }
        }
    }
}

# Function to run tests
function Run-Tests {
    if ($Test -or $Coverage) {
        Write-Status "Running tests..."
        
        if (Test-CommandExists "pytest") {
            if ($Coverage) {
                & pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
            }
            else {
                & pytest tests/
            }
        }
        else {
            Write-WarningMsg "pytest not found, skipping tests"
        }
    }
}

# Function to validate build
function Validate-Build {
    Write-Status "Validating build..."
    # Prefer installed rev CLI; fallback to python -m rev
    $revCmd = Get-Command rev -ErrorAction SilentlyContinue
    if ($revCmd) {
        try {
            & rev --help *> $null
            if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 2) {
                Write-Status "rev CLI executes successfully"
            }
            else {
                Write-WarningMsg "rev help command failed (may require Ollama)"
            }
        }
        catch {
            Write-WarningMsg "rev help command failed (may require Ollama)"
        }
    }
    else {
        try {
            & python -m rev --help *> $null
            if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 2) {
                Write-Status "python -m rev executes successfully"
            }
            else {
                Write-ErrorExit "rev CLI not found and python -m rev failed"
            }
        }
        catch {
            Write-ErrorExit "rev CLI not found and python -m rev failed"
        }
    }
}

function Stamp-GitCommit {
    # Update rev/_version.py with current git commit for packaged artifacts
    try {
        $repoRoot = Split-Path $PSScriptRoot
        $commit = git -C $repoRoot rev-parse HEAD 2>$null
        if (-not $commit) {
            Write-WarningMsg "Git commit not found; leaving REV_GIT_COMMIT unchanged"
            return
        }
        $versionFile = Join-Path $repoRoot "rev\_version.py"
        if (-not (Test-Path $versionFile)) {
            Write-WarningMsg "Version file not found at $versionFile"
            return
        }
        $content = Get-Content $versionFile -Raw
        $newContent = $content -replace 'REV_GIT_COMMIT\s*=\s*".*"', "REV_GIT_COMMIT = `"$commit`""
        Set-Content $versionFile $newContent -Encoding UTF8
        Write-Status "Stamped REV_GIT_COMMIT=$($commit.Substring(0,7))"
    }
    catch {
        Write-WarningMsg "Failed to stamp git commit: $($_.Exception.Message)"
    }
}

function Build-Wheel {
    Write-Status "Building wheel..."
    if (-not (Test-CommandExists "python")) {
        Write-ErrorExit "Python not found for build"
    }
    & python -m build
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorExit "Wheel build failed"
    }
}

function Publish-Package {
    param([string]$Repository = "pypi")
    Write-Status "Publishing to $Repository via twine..."
    if (-not (Test-CommandExists "twine")) {
        Write-ErrorExit "twine not installed. Install with: pip install twine"
    }
    & twine upload --repository $Repository dist/*
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorExit "twine upload failed"
    }
}

# Function to clean build artifacts
function Clean-Build {
    Write-Status "Cleaning build artifacts..."
    
    # Remove Python cache files
    Get-ChildItem -Path . -Include "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path . -Include "*.pyc","*.pyo","*~",".*~" -Recurse -File | Remove-Item -Force -ErrorAction SilentlyContinue
    
    # Remove test temporary directories
    if (Test-Path "tests_tmp_agent_min") {
        Remove-Item -Path "tests_tmp_agent_min" -Recurse -Force -ErrorAction SilentlyContinue
    }
    
    # Remove coverage reports
    if (Test-Path "htmlcov") {
        Remove-Item -Path "htmlcov" -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path ".coverage") {
        Remove-Item -Path ".coverage" -Force -ErrorAction SilentlyContinue
    }
    
    # Remove virtual environment if requested
    if ($CleanVenv) {
        if (Test-Path ".venv") {
            Remove-Item -Path ".venv" -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Status "Virtual environment removed"
    }
    
    Write-Status "Build artifacts cleaned"
}

# Function to show help
function Show-Help {
    Write-Host "Usage: .\build.ps1 [OPTIONS]"
    Write-Host ""
    Write-Host "Options:"
    Write-Host "  -Dev         Install development dependencies"
    Write-Host "  -Full        Install full dependencies"
    Write-Host "  -Test        Run tests"
    Write-Host "  -Coverage    Run tests with coverage report"
    Write-Host "  -Clean       Clean build artifacts"
    Write-Host "  -CleanVenv   Clean build artifacts and virtual environment"
    Write-Host "  -Publish     Stamp commit, build wheel, and upload via twine"
    Write-Host "  -Help        Show this help message"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\build.ps1                    # Basic setup"
    Write-Host "  .\build.ps1 -Dev -Test         # Development setup with tests"
    Write-Host "  .\build.ps1 -Full -Coverage    # Full setup with coverage"
    Write-Host "  .\build.ps1 -Publish           # Stamp commit, build, and upload"
}

# Main function
function Main {
    Write-Host "================================" -ForegroundColor $BLUE
    Write-Host "  $SCRIPT_NAME v$SCRIPT_VERSION" -ForegroundColor $BLUE
    Write-Host "================================" -ForegroundColor $BLUE
    Write-Host ""
    
    # Handle help
    if ($Help) {
        Show-Help
        return
    }
    
    # Handle clean
    if ($Clean -or $CleanVenv) {
        Clean-Build
        return
    }
    
    Write-Host "Starting build process..." -ForegroundColor $BLUE
    Write-Host ""
    
    # Check Python version
    Check-PythonVersion
    
    # Create and activate virtual environment
    Create-Venv
    
    # Upgrade pip
    Write-Status "Upgrading pip..."
    & pip install --upgrade pip
    
    # Install dependencies
    Install-Dependencies
    
    # Run tests if requested
    Run-Tests
    
    # Validate build
    Validate-Build

    # Stamp commit and build wheel/sdist
    Stamp-GitCommit
    Build-Wheel

    if ($Publish) {
        Publish-Package
    }
    
    Write-Host ""
    Write-Host "================================" -ForegroundColor $GREEN
    Write-Host "  Build completed successfully!" -ForegroundColor $GREEN
    Write-Host "================================" -ForegroundColor $GREEN
    
    if (Test-VenvActive) {
        Write-Host "Virtual environment is active:" -ForegroundColor $BLUE
        Write-Host "  $env:VIRTUAL_ENV" -ForegroundColor $WHITE
        Write-Host "To deactivate, run:" -ForegroundColor $BLUE
        Write-Host "  deactivate" -ForegroundColor $WHITE
    }
    
    Write-Host ""
    Write-Host "Quick start:" -ForegroundColor $BLUE
    Write-Host "  rev --help" -ForegroundColor $WHITE
    Write-Host "  rev ""Add error handling to API endpoints""" -ForegroundColor $WHITE
    Write-Host ""
}

# Handle command line arguments
if ($Help) {
    Show-Help
}
elseif ($Clean -or $CleanVenv) {
    Clean-Build
}
else {
    Main
}
