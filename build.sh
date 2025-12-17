#!/bin/bash
# Build script for rev - Autonomous CI/CD Agent
# This script sets up the environment and runs the build process

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script information
SCRIPT_NAME="rev Build Script"
SCRIPT_VERSION="1.0.0"

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  $SCRIPT_NAME v$SCRIPT_VERSION${NC}"
echo -e "${BLUE}================================${NC}"
echo

# Function to print status messages
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

# Function to print warning messages
print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

# Function to print error messages
print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check Python version
check_python_version() {
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        PYTHON_CMD="python"
    else
        print_error "Python is not installed"
        exit 1
    fi

    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)

    if [[ $PYTHON_MAJOR -lt 3 ]] || [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 7 ]]; then
        print_error "Python 3.7 or higher is required. Found Python $PYTHON_VERSION"
        exit 1
    fi

    print_status "Python version: $PYTHON_VERSION"
}

# Function to check if virtual environment is active
is_venv_active() {
    if [[ -n "$VIRTUAL_ENV" ]]; then
        return 0
    else
        return 1
    fi
}

# Function to create virtual environment
create_venv() {
    if is_venv_active; then
        print_status "Virtual environment already active: $VIRTUAL_ENV"
        return 0
    fi

    VENV_DIR=".venv"
    
    if [[ ! -d "$VENV_DIR" ]]; then
        print_status "Creating virtual environment..."
        $PYTHON_CMD -m venv "$VENV_DIR"
    fi

    # Activate virtual environment
    if [[ -f "$VENV_DIR/bin/activate" ]]; then
        source "$VENV_DIR/bin/activate"
        print_status "Virtual environment activated"
    else
        print_error "Failed to activate virtual environment"
        exit 1
    fi
}

# Function to detect project type
detect_project_type() {
    if [[ -f "requirements.txt" ]] || [[ -f "pyproject.toml" ]]; then
        PROJECT_TYPE="python"
    elif [[ -f "package.json" ]]; then
        PROJECT_TYPE="javascript"
    elif [[ -f "Cargo.toml" ]]; then
        PROJECT_TYPE="rust"
    elif [[ -f "go.mod" ]]; then
        PROJECT_TYPE="go"
    else
        PROJECT_TYPE="unknown"
    fi
    print_status "Detected project type: $PROJECT_TYPE"
}

# Function to install dependencies
install_dependencies() {
    print_status "Installing dependencies for $PROJECT_TYPE project..."
    
    case $PROJECT_TYPE in
        python)
            pip install --upgrade pip
            if [[ -f "requirements.txt" ]]; then
                pip install -r requirements.txt
                print_status "Minimal requirements installed"
            fi
            if [[ "$INSTALL_DEV" == "true" && -f "requirements-dev.txt" ]]; then
                pip install -r requirements-dev.txt
                print_status "Development requirements installed"
            fi
            if [[ "$INSTALL_FULL" == "true" && -f "requirements-full.txt" ]]; then
                pip install -r requirements-full.txt
                print_status "Full requirements installed"
            fi
            ;;
        javascript)
            if command_exists npm; then
                npm install
                print_status "Dependencies installed"
            else
                print_error "npm is not installed"
                exit 1
            fi
            ;;
        *)
            print_warning "Unsupported project type: $PROJECT_TYPE"
            ;;
    esac
}

# Function to run tests
run_tests() {
    if [[ "$RUN_TESTS" == "true" ]]; then
        print_status "Running tests..."
        
        if command_exists pytest; then
            if [[ "$WITH_COVERAGE" == "true" ]]; then
                pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
            else
                pytest tests/
            fi
        else
            print_warning "pytest not found, skipping tests"
        fi
    fi
}

# Function to validate build
validate_build() {
    print_status "Validating build..."
    
    # Check if rev CLI is available; fallback to python -m rev
    if command -v rev >/dev/null 2>&1; then
        if rev --help >/dev/null 2>&1; then
            print_status "rev CLI executes successfully"
        else
            print_warning "rev help command failed (may require Ollama)"
        fi
    else
        if python -m rev --help >/dev/null 2>&1; then
            print_status "python -m rev executes successfully"
        else
            print_error "rev CLI not found and python -m rev failed"
            exit 1
        fi
    fi
}

# Function to clean build artifacts
clean_build() {
    print_status "Cleaning build artifacts..."
    
    # Remove Python cache files
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type f -name "*.pyo" -delete 2>/dev/null || true
    find . -type f -name "*~" -delete 2>/dev/null || true
    find . -type f -name ".*~" -delete 2>/dev/null || true
    
    # Remove test temporary directories
    rm -rf tests_tmp_agent_min 2>/dev/null || true
    
    # Remove coverage reports
    rm -rf htmlcov 2>/dev/null || true
    rm -f .coverage 2>/dev/null || true
    
    # Remove virtual environment if requested
    if [[ "$CLEAN_VENV" == "true" ]]; then
        rm -rf .venv 2>/dev/null || true
        print_status "Virtual environment removed"
    fi
    
    print_status "Build artifacts cleaned"
}

# Default options
INSTALL_DEV=false
INSTALL_FULL=false
RUN_TESTS=false
WITH_COVERAGE=false
CLEAN_VENV=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            INSTALL_DEV=true
            shift
            ;;
        --full)
            INSTALL_FULL=true
            shift
            ;;
        --test)
            RUN_TESTS=true
            shift
            ;;
        --coverage)
            RUN_TESTS=true
            WITH_COVERAGE=true
            shift
            ;;
        --clean)
            clean_build
            exit 0
            ;;
        --clean-venv)
            CLEAN_VENV=true
            clean_build
            exit 0
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dev         Install development dependencies"
            echo "  --full        Install full dependencies"
            echo "  --test        Run tests"
            echo "  --coverage    Run tests with coverage report"
            echo "  --clean       Clean build artifacts"
            echo "  --clean-venv  Clean build artifacts and virtual environment"
            echo "  --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Basic setup"
            echo "  $0 --dev --test       # Development setup with tests"
            echo "  $0 --full --coverage  # Full setup with coverage"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Main build process
main() {
    echo -e "${BLUE}Starting build process...${NC}"
    echo
    
    # Check Python version
    check_python_version
    
    # Detect project type
    detect_project_type

    # Create and activate virtual environment for Python projects
    if [[ "$PROJECT_TYPE" == "python" ]]; then
        create_venv
    fi

    # Install dependencies
    install_dependencies
    
    # Run tests if requested
    run_tests
    
    # Validate build
    validate_build
    
    echo
    echo -e "${GREEN}================================${NC}"
    echo -e "${GREEN}  Build completed successfully!${NC}"
    echo -e "${GREEN}================================${NC}"
    
    if is_venv_active; then
        echo -e "${BLUE}Virtual environment is active:${NC} $VIRTUAL_ENV"
        echo -e "${BLUE}To deactivate, run:${NC} deactivate"
    fi
    
    echo
    echo -e "${BLUE}Quick start:${NC}"
    echo -e "  rev --help"
    echo -e "  rev \"Add error handling to API endpoints\""
    echo
}

# Run main function
main
