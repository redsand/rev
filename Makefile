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
	@echo "$(GREEN)Examples:$(NC)"
	@echo "  make setup    # Basic setup"
	@echo "  make dev test # Development setup with tests"
	@echo "  make full coverage # Full setup with coverage"

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

# Default target
.PHONY: all
all: setup validate