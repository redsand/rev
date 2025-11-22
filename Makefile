# Makefile for rev.py - Autonomous CI/CD Agent

# Variables
PYTHON := python3
PIP := pip3
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
VENV_PYTHON := $(VENV_BIN)/python
VENV_PIP := $(VENV_BIN)/pip

# Colors
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
NC := \033[0m # No Color

# Check if virtual environment exists
ifeq ($(wildcard $(VENV_DIR)/.),)
	VENV_ACTIVE := false
else
	VENV_ACTIVE := true
endif

# Default target
.PHONY: help
help:
	@echo "$(BLUE)================================$(NC)"
	@echo "$(BLUE)  rev.py Build System$(NC)"
	@echo "$(BLUE)================================$(NC)"
	@echo ""
	@echo "$(GREEN)Available targets:$(NC)"
	@echo "  help          - Show this help message"
	@echo "  setup         - Basic setup (minimal dependencies)"
	@echo "  dev           - Development setup (dev dependencies)"
	@echo "  full          - Full setup (all dependencies)"
	@echo "  test          - Run tests"
	@echo "  coverage      - Run tests with coverage report"
	@echo "  clean         - Clean build artifacts"
	@echo "  clean-venv    - Clean build artifacts and virtual environment"
	@echo "  validate      - Validate build"
	@echo "  shell         - Activate virtual environment shell"
	@echo ""
	@echo "$(GREEN)Static Analysis:$(NC)"
	@echo "  lint          - Run all linters (pylint, mypy, bandit)"
	@echo "  pylint        - Run pylint code analysis"
	@echo "  mypy          - Run mypy type checking"
	@echo "  bandit        - Run bandit security scanning"
	@echo "  complexity    - Analyze code complexity with radon"
	@echo "  deadcode      - Find unused code with vulture"
	@echo "  analyze       - Run complete analysis suite"
	@echo ""
	@echo "$(GREEN)Examples:$(NC)"
	@echo "  make setup    # Basic setup"
	@echo "  make dev test # Development setup with tests"
	@echo "  make lint     # Run all linters"
	@echo "  make analyze  # Full code analysis"

# Create virtual environment
.PHONY: venv
venv:
	@if [ "$(VENV_ACTIVE)" = "false" ]; then \
		echo "$(BLUE)Creating virtual environment...$(NC)"; \
		$(PYTHON) -m venv $(VENV_DIR); \
	else \
		echo "$(GREEN)Virtual environment already exists$(NC)"; \
	fi

# Activate virtual environment and upgrade pip
.PHONY: activate
activate: venv
	@if [ "$(VENV_ACTIVE)" = "false" ]; then \
		echo "$(YELLOW)Please activate the virtual environment:$(NC)"; \
		echo "  source $(VENV_DIR)/bin/activate"; \
	else \
		echo "$(GREEN)Virtual environment is active$(NC)"; \
	fi
	@echo "$(BLUE)Upgrading pip...$(NC)"
	@$(VENV_PIP) install --upgrade pip

# Basic setup
.PHONY: setup
setup: activate
	@echo "$(BLUE)Installing minimal dependencies...$(NC)"
	@if [ -f requirements.txt ]; then \
		$(VENV_PIP) install -r requirements.txt; \
		echo "$(GREEN)Minimal requirements installed$(NC)"; \
	else \
		echo "$(YELLOW)requirements.txt not found$(NC)"; \
	fi

# Development setup
.PHONY: dev
dev: setup
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	@if [ -f requirements-dev.txt ]; then \
		$(VENV_PIP) install -r requirements-dev.txt; \
		echo "$(GREEN)Development requirements installed$(NC)"; \
	else \
		echo "$(YELLOW)requirements-dev.txt not found$(NC)"; \
	fi

# Full setup
.PHONY: full
full: setup
	@echo "$(BLUE)Installing full dependencies...$(NC)"
	@if [ -f requirements-full.txt ]; then \
		$(VENV_PIP) install -r requirements-full.txt; \
		echo "$(GREEN)Full requirements installed$(NC)"; \
	else \
		echo "$(YELLOW)requirements-full.txt not found$(NC)"; \
	fi

# Run tests
.PHONY: test
test:
	@echo "$(BLUE)Running tests...$(NC)"
	@if command -v pytest >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m pytest tests/; \
	elif [ -f $(VENV_BIN)/pytest ]; then \
		$(VENV_BIN)/pytest tests/; \
	else \
		echo "$(YELLOW)pytest not found, installing...$(NC)"; \
		$(VENV_PIP) install pytest; \
		$(VENV_PYTHON) -m pytest tests/; \
	fi

# Run tests with coverage
.PHONY: coverage
coverage:
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	@if command -v pytest >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html; \
	elif [ -f $(VENV_BIN)/pytest ]; then \
		$(VENV_BIN)/pytest tests/ --cov=. --cov-report=term-missing --cov-report=html; \
	else \
		echo "$(YELLOW)pytest not found, installing...$(NC)"; \
		$(VENV_PIP) install pytest pytest-cov; \
		$(VENV_PYTHON) -m pytest tests/ --cov=. --cov-report=term-missing --cov-report=html; \
	fi

# Validate build
.PHONY: validate
validate:
	@echo "$(BLUE)Validating build...$(NC)"
	@if [ -f rev.py ]; then \
		echo "$(GREEN)rev.py found$(NC)"; \
		if $(VENV_PYTHON) rev.py --help >/dev/null 2>&1; then \
			echo "$(GREEN)rev.py executes successfully$(NC)"; \
		else \
			echo "$(YELLOW)rev.py help command failed (may require Ollama)$(NC)"; \
		fi; \
	else \
		echo "$(RED)rev.py not found$(NC)"; \
		exit 1; \
	fi

# Clean build artifacts
.PHONY: clean
clean:
	@echo "$(BLUE)Cleaning build artifacts...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*~" -delete 2>/dev/null || true
	@find . -type f -name ".*~" -delete 2>/dev/null || true
	@rm -rf tests_tmp_agent_min 2>/dev/null || true
	@rm -rf htmlcov 2>/dev/null || true
	@rm -f .coverage 2>/dev/null || true
	@echo "$(GREEN)Build artifacts cleaned$(NC)"

# Clean everything including virtual environment
.PHONY: clean-venv
clean-venv: clean
	@echo "$(BLUE)Removing virtual environment...$(NC)"
	@rm -rf $(VENV_DIR) 2>/dev/null || true
	@echo "$(GREEN)Virtual environment removed$(NC)"

# Activate virtual environment shell
.PHONY: shell
shell:
	@if [ -f $(VENV_DIR)/bin/activate ]; then \
		echo "$(BLUE)Activating virtual environment...$(NC)"; \
		echo "$(YELLOW)To deactivate, run: deactivate$(NC)"; \
		exec bash --rcfile $(VENV_DIR)/bin/activate; \
	else \
		echo "$(RED)Virtual environment not found. Run 'make setup' first.$(NC)"; \
		exit 1; \
	fi

# Static analysis targets
.PHONY: pylint
pylint:
	@echo "$(BLUE)Running pylint...$(NC)"
	@if command -v pylint >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m pylint rev/ --rcfile=.pylintrc || true; \
	elif [ -f $(VENV_BIN)/pylint ]; then \
		$(VENV_BIN)/pylint rev/ --rcfile=.pylintrc || true; \
	else \
		echo "$(YELLOW)pylint not found, installing...$(NC)"; \
		$(VENV_PIP) install pylint; \
		$(VENV_PYTHON) -m pylint rev/ --rcfile=.pylintrc || true; \
	fi

.PHONY: mypy
mypy:
	@echo "$(BLUE)Running mypy type checking...$(NC)"
	@if command -v mypy >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m mypy rev/ --config-file=mypy.ini || true; \
	elif [ -f $(VENV_BIN)/mypy ]; then \
		$(VENV_BIN)/mypy rev/ --config-file=mypy.ini || true; \
	else \
		echo "$(YELLOW)mypy not found, installing...$(NC)"; \
		$(VENV_PIP) install mypy; \
		$(VENV_PYTHON) -m mypy rev/ --config-file=mypy.ini || true; \
	fi

.PHONY: bandit
bandit:
	@echo "$(BLUE)Running bandit security scanning...$(NC)"
	@if command -v bandit >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m bandit -r rev/ -f screen || true; \
	elif [ -f $(VENV_BIN)/bandit ]; then \
		$(VENV_BIN)/bandit -r rev/ -f screen || true; \
	else \
		echo "$(YELLOW)bandit not found, installing...$(NC)"; \
		$(VENV_PIP) install bandit; \
		$(VENV_PYTHON) -m bandit -r rev/ -f screen || true; \
	fi

.PHONY: complexity
complexity:
	@echo "$(BLUE)Analyzing code complexity...$(NC)"
	@if command -v radon >/dev/null 2>&1; then \
		echo "$(GREEN)Cyclomatic Complexity:$(NC)"; \
		$(VENV_PYTHON) -m radon cc rev/ -a -s || true; \
		echo ""; \
		echo "$(GREEN)Maintainability Index:$(NC)"; \
		$(VENV_PYTHON) -m radon mi rev/ -s || true; \
	elif [ -f $(VENV_BIN)/radon ]; then \
		echo "$(GREEN)Cyclomatic Complexity:$(NC)"; \
		$(VENV_BIN)/radon cc rev/ -a -s || true; \
		echo ""; \
		echo "$(GREEN)Maintainability Index:$(NC)"; \
		$(VENV_BIN)/radon mi rev/ -s || true; \
	else \
		echo "$(YELLOW)radon not found, installing...$(NC)"; \
		$(VENV_PIP) install radon; \
		echo "$(GREEN)Cyclomatic Complexity:$(NC)"; \
		$(VENV_PYTHON) -m radon cc rev/ -a -s || true; \
		echo ""; \
		echo "$(GREEN)Maintainability Index:$(NC)"; \
		$(VENV_PYTHON) -m radon mi rev/ -s || true; \
	fi

.PHONY: deadcode
deadcode:
	@echo "$(BLUE)Finding dead code...$(NC)"
	@if command -v vulture >/dev/null 2>&1; then \
		$(VENV_PYTHON) -m vulture rev/ --min-confidence 80 || true; \
	elif [ -f $(VENV_BIN)/vulture ]; then \
		$(VENV_BIN)/vulture rev/ --min-confidence 80 || true; \
	else \
		echo "$(YELLOW)vulture not found, installing...$(NC)"; \
		$(VENV_PIP) install vulture; \
		$(VENV_PYTHON) -m vulture rev/ --min-confidence 80 || true; \
	fi

.PHONY: lint
lint: pylint mypy bandit
	@echo "$(GREEN)All linters completed$(NC)"

.PHONY: analyze
analyze: lint complexity deadcode
	@echo "$(GREEN)Complete analysis finished$(NC)"

# Default target
.PHONY: all
all: setup validate