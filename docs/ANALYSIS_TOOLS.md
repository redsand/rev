# Static Analysis Tools for rev

This document describes the comprehensive cross-platform static analysis tools integrated into rev.

## Overview

Rev now includes powerful AST-based and static analysis tools that work on **Windows, Linux, and macOS**. These tools help maintain code quality, catch bugs early, and improve security.

## Available Tools

### 1. AST-Based Pattern Analysis (Built-in)
**Tool**: `analyze_ast_patterns`
**Language**: Python (built-in `ast` module)
**Cross-platform**: ✅ Yes

Uses Python's Abstract Syntax Tree for accurate code pattern matching. More reliable than regex for code analysis.

**Detects**:
- TODO/FIXME comments
- Print statements (potential debug code)
- Dangerous functions (`eval`, `exec`, `compile`, `__import__`)
- Missing type hints
- Complex functions (many parameters)
- Global variable usage

**Usage**:
```python
from rev.tools.analysis import analyze_ast_patterns

# Analyze specific patterns
result = analyze_ast_patterns("path/to/code", patterns=["todos", "dangerous"])

# Analyze all patterns
result = analyze_ast_patterns("path/to/code")
```

**Via Makefile**: N/A (integrated into agent tools)

---

### 2. Pylint - Comprehensive Static Analysis
**Tool**: `run_pylint`
**Cross-platform**: ✅ Yes
**Install**: `pip install pylint`

Comprehensive code analysis checking for errors, style violations, code smells, and anti-patterns.

**Checks**:
- Code errors and bugs
- PEP 8 style violations
- Code smells and anti-patterns
- Unused imports and variables
- Naming conventions
- Code complexity

**Usage**:
```python
from rev.tools.analysis import run_pylint

# Use default config
result = run_pylint("path/to/code")

# Use custom config
result = run_pylint("path/to/code", config=".pylintrc")
```

**Via Makefile**:
```bash
make pylint    # Run pylint with project config
```

**Configuration**: `.pylintrc` (already configured for rev)

---

### 3. Mypy - Static Type Checking
**Tool**: `run_mypy`
**Cross-platform**: ✅ Yes
**Install**: `pip install mypy`

Static type checker that verifies type hints and catches type-related bugs before runtime.

**Checks**:
- Type hint consistency
- Type errors (passing wrong types)
- None/Optional handling
- Return type validation

**Usage**:
```python
from rev.tools.analysis import run_mypy

# Use default config
result = run_mypy("path/to/code")

# Use custom config
result = run_mypy("path/to/code", config="mypy.ini")
```

**Via Makefile**:
```bash
make mypy      # Run mypy type checking
```

**Configuration**: `mypy.ini` (already configured for rev)

---

### 4. Bandit - Security Scanner
**Tool**: Already integrated via `rev.tools.security.scan_code_security`
**Cross-platform**: ✅ Yes
**Install**: `pip install bandit`

Scans Python code for common security vulnerabilities.

**Detects**:
- SQL injection vulnerabilities
- Hardcoded passwords/secrets
- Use of unsafe functions
- Weak cryptography
- Command injection risks

**Usage**:
```python
from rev.tools.security import scan_code_security

result = scan_code_security("path/to/code", tool="bandit")
```

**Via Makefile**:
```bash
make bandit    # Run bandit security scan
```

---

### 5. Radon - Code Complexity Metrics
**Tool**: `run_radon_complexity`
**Cross-platform**: ✅ Yes
**Install**: `pip install radon`

Analyzes code complexity to identify hard-to-maintain code.

**Metrics**:
- **Cyclomatic Complexity**: Number of paths through code (lower is better)
  - A: 1-5 (simple)
  - B: 6-10 (moderate)
  - C: 11-20 (complex)
  - D: 21-50 (very complex)
  - E: 51-100 (extremely complex)
  - F: 100+ (unmaintainable)

- **Maintainability Index**: Code maintainability score (higher is better)
  - A: 20-100 (maintainable)
  - B: 10-19 (moderately maintainable)
  - C: 0-9 (difficult to maintain)

- **Raw Metrics**: LOC, SLOC, comments, blank lines

**Usage**:
```python
from rev.tools.analysis import run_radon_complexity

# Report functions with complexity C or higher
result = run_radon_complexity("path/to/code", min_rank="C")
```

**Via Makefile**:
```bash
make complexity    # Analyze code complexity
```

---

### 6. Vulture - Dead Code Detection
**Tool**: `find_dead_code`
**Cross-platform**: ✅ Yes
**Install**: `pip install vulture`

Finds unused and unreachable code.

**Detects**:
- Unused functions and classes
- Unused variables
- Unused imports
- Unused properties and attributes
- Unreachable code

**Usage**:
```python
from rev.tools.analysis import find_dead_code

# Find dead code with 80%+ confidence
result = find_dead_code("path/to/code")
```

**Via Makefile**:
```bash
make deadcode      # Find unused code
```

---

### 7. Combined Analysis
**Tool**: `run_all_analysis`
**Cross-platform**: ✅ Yes

Runs all available analysis tools and combines results into a comprehensive report.

**Usage**:
```python
from rev.tools.analysis import run_all_analysis

# Run everything
result = run_all_analysis("path/to/code")
```

**Via Makefile**:
```bash
make lint          # Run pylint + mypy + bandit
make analyze       # Run all analysis tools
```

---

## Installation

### Quick Start
```bash
# Install all analysis tools
make dev

# Or install manually
pip install -r requirements-dev.txt
```

### Individual Tools
```bash
pip install pylint mypy bandit radon vulture
```

---

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make pylint` | Run pylint code analysis |
| `make mypy` | Run mypy type checking |
| `make bandit` | Run bandit security scanning |
| `make complexity` | Analyze code complexity with radon |
| `make deadcode` | Find unused code with vulture |
| `make lint` | Run all linters (pylint + mypy + bandit) |
| `make analyze` | Run complete analysis suite |

---

## Integration with rev Agents

All analysis tools are automatically available to rev agents through the tool registry:

```python
# Available tools for LLM agents:
- analyze_ast_patterns
- run_pylint
- run_mypy
- run_radon_complexity
- find_dead_code
- run_all_analysis
- scan_code_security (bandit)
```

Agents can call these tools during:
- Code review
- Pre-commit validation
- Security audits
- Refactoring analysis
- Quality checks

---

## Configuration Files

### `.pylintrc`
Pylint configuration tuned for rev project standards:
- PEP 8 with 120 char line length
- Relaxed docstring requirements
- Balanced complexity limits

### `mypy.ini`
Mypy configuration for gradual typing:
- Python 3.8+ compatibility
- Ignore missing imports for third-party libs
- Per-module strictness configuration

---

## Why AST-based Analysis?

Traditional regex-based code search has limitations:
- ❌ Can't understand code structure
- ❌ Misses context-dependent patterns
- ❌ High false positive rate
- ❌ Fragile to formatting changes

AST-based analysis:
- ✅ Understands Python syntax perfectly
- ✅ Context-aware pattern matching
- ✅ Low false positive rate
- ✅ Robust to code formatting
- ✅ Cross-platform (pure Python)

---

## Cross-Platform Compatibility

All tools are **100% cross-platform**:
- ✅ **Windows**: Works natively (including your Windows setup)
- ✅ **Linux**: Native support
- ✅ **macOS**: Native support

Unlike platform-specific tools:
- ❌ Valgrind (Linux-only)
- ❌ AddressSanitizer (requires LLVM/Clang compilation)
- ❌ Windows-specific analyzers

---

## Best Practices

1. **Run regularly**: Include in CI/CD pipeline
2. **Fix high-severity issues first**: Security > Errors > Warnings > Style
3. **Use incrementally**: Don't try to fix everything at once
4. **Configure for your project**: Adjust `.pylintrc` and `mypy.ini` as needed
5. **Combine tools**: Each tool catches different issues

---

## Example Workflow

```bash
# 1. Install dev dependencies
make dev

# 2. Run quick lint check
make lint

# 3. Check code complexity
make complexity

# 4. Find dead code
make deadcode

# 5. Full analysis before commit
make analyze
```

---

## Troubleshooting

### Tool not found
```bash
# Install missing tools
make dev

# Or individually
pip install pylint mypy bandit radon vulture
```

### Too many warnings
Edit configuration files to adjust strictness:
- `.pylintrc`: Disable specific checks
- `mypy.ini`: Adjust type checking strictness

### False positives
- **Pylint**: Add `# pylint: disable=check-name` comments
- **Mypy**: Add `# type: ignore` comments
- **Vulture**: Add whitelist file for intentional "unused" code
- **Bandit**: Add `# nosec` comments for safe code flagged as risky

---

## Next Steps

- [ ] Integrate analysis into CI/CD pipeline
- [ ] Add pre-commit hooks for automatic analysis
- [ ] Create custom AST patterns for project-specific checks
- [ ] Set up automated analysis reports

---

## References

- [Pylint Documentation](https://pylint.readthedocs.io/)
- [Mypy Documentation](https://mypy.readthedocs.io/)
- [Bandit Documentation](https://bandit.readthedocs.io/)
- [Radon Documentation](https://radon.readthedocs.io/)
- [Vulture Documentation](https://github.com/jendrikseipp/vulture)
- [Python AST Module](https://docs.python.org/3/library/ast.html)
