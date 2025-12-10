# Advanced Utilities

rev includes powerful utilities for file conversion, code refactoring, dependency management, and security scanning.

## File Format Conversion

Convert between common file formats without external tools.

### JSON ↔ YAML

```python
# Convert JSON to YAML
convert_json_to_yaml("config.json")  # Creates config.yaml
convert_json_to_yaml("data.json", "output.yaml")  # Custom output

# Convert YAML to JSON
convert_yaml_to_json("docker-compose.yaml")  # Creates docker-compose.json
convert_yaml_to_json(".github/workflows/ci.yml", "ci-config.json")
```

**Use Cases:**
- Convert Kubernetes manifests between formats
- Transform CI/CD configs
- API configuration management

### CSV ↔ JSON

```python
# Convert CSV to JSON array of objects
convert_csv_to_json("users.csv")  # Creates users.json
# Result: [{"name": "John", "age": "30"}, ...]

# Convert JSON array to CSV
convert_json_to_csv("data.json", "report.csv")
```

**Use Cases:**
- Data analysis and reporting
- Import/export data
- API response transformation

### Environment Files

```python
# Convert .env to JSON
convert_env_to_json(".env")  # Creates .env.json
convert_env_to_json(".env.production", "prod-config.json")
```

**Use Cases:**
- Configuration management
- Environment variable documentation
- Config file generation

## Code Refactoring Utilities

Automated code improvement and analysis tools.

### Remove Unused Imports

Automatically clean up unused imports in your code:

```python
# Python files
remove_unused_imports("app.py", language="python")
remove_unused_imports("src/services/user.py")
```

**Requirements:** `pip install autoflake`

**Before:**
```python
import os
import sys
import json  # unused
from pathlib import Path  # unused

def main():
    print(os.path.abspath('.'))
```

**After:**
```python
import os

def main():
    print(os.path.abspath('.'))
```

### Extract Constants

Identify "magic numbers" and strings that should be constants:

```python
extract_constants("app.py", threshold=3)
```

**Output:**
```json
{
  "file": "app.py",
  "suggestions": [
    {
      "type": "number",
      "value": "8080",
      "occurrences": 5,
      "suggested_name": "CONSTANT_8080"
    },
    {
      "type": "string",
      "value": "database connection failed",
      "occurrences": 4,
      "suggested_name": "DATABASE_CONNECTION_FAILED"
    }
  ],
  "count": 2
}
```

**Before:**
```python
server = Server(8080)
backup = Server(8080)
fallback = Server(8080)
```

**Suggested Refactoring:**
```python
DEFAULT_PORT = 8080
server = Server(DEFAULT_PORT)
backup = Server(DEFAULT_PORT)
fallback = Server(DEFAULT_PORT)
```

### Simplify Complex Conditionals

Find overly complex if statements:

```python
simplify_conditionals("src/validator.py")
```

**Output:**
```json
{
  "file": "src/validator.py",
  "complex_conditionals": [
    {
      "line": 45,
      "issue": "Complex conditional",
      "complexity": 5,
      "suggestion": "Consider extracting to a boolean variable or method"
    }
  ],
  "count": 1
}
```

**Before:**
```python
if user.age >= 18 and user.verified and (user.role == 'admin' or user.role == 'moderator') and not user.suspended and user.email_confirmed:
    allow_access()
```

**Suggested Refactoring:**
```python
def can_access(user):
    is_adult = user.age >= 18
    is_authorized = user.role in ['admin', 'moderator']
    is_valid_account = user.verified and user.email_confirmed and not user.suspended
    return is_adult and is_authorized and is_valid_account

if can_access(user):
    allow_access()
```

## Dependency Management

Analyze and manage project dependencies across multiple languages.

### Analyze Dependencies

Check dependencies for issues:

```python
# Auto-detect language from project files
analyze_dependencies()  # Checks requirements.txt or package.json

# Specify language explicitly
analyze_dependencies(language="python")
analyze_dependencies(language="javascript")
```

**Python Output:**
```json
{
  "language": "python",
  "dependencies": ["requests==2.28.0", "flask>=2.0.0", "pytest"],
  "count": 3,
  "file": "requirements.txt",
  "issues": [
    {
      "type": "unpinned_versions",
      "count": 2,
      "packages": ["flask>=2.0.0", "pytest"]
    },
    {
      "type": "no_virtual_environment",
      "message": "No virtual environment detected"
    }
  ]
}
```

**JavaScript Output:**
```json
{
  "language": "javascript",
  "dependencies": ["express", "lodash", "axios"],
  "dev_dependencies": ["jest", "eslint"],
  "count": 5,
  "file": "package.json",
  "issues": [
    {
      "type": "flexible_versions",
      "count": 3,
      "message": "Using ^ or ~ version ranges",
      "packages": ["express@^4.18.0", "lodash@~4.17.0"]
    }
  ]
}
```

### Update Dependencies

Check for outdated packages:

```python
# Check for updates
update_dependencies()  # Auto-detects language
update_dependencies(language="python")
update_dependencies(language="javascript", major=True)
```

**Output:**
```json
{
  "language": "python",
  "outdated": [
    {
      "name": "requests",
      "version": "2.28.0",
      "latest_version": "2.31.0",
      "latest_filetype": "wheel"
    }
  ],
  "count": 1,
  "message": "Use 'pip install --upgrade <package>' to update"
}
```

**Supported Languages:**
- Python (requirements.txt, pyproject.toml)
- JavaScript/Node.js (package.json)
- Rust (Cargo.toml) - detection only
- Go (go.mod) - detection only

## Security Scanning

Comprehensive security analysis for code and dependencies.

### Dependency Vulnerability Scanning

Scan dependencies for known security vulnerabilities:

```python
# Auto-detect language
scan_dependencies_vulnerabilities()

# Specify language
scan_dependencies_vulnerabilities(language="python")
scan_dependencies_vulnerabilities(language="javascript")
```

**Python Tools Used:**
- `safety` - PyPI vulnerability database
- `pip-audit` - Python package auditing

**JavaScript Tools Used:**
- `npm audit` - NPM security audit

**Output:**
```json
{
  "language": "python",
  "tool": "safety",
  "vulnerabilities": [
    {
      "package": "django",
      "installed_version": "2.2.0",
      "affected": "<2.2.28",
      "vulnerability": "CVE-2022-28346",
      "severity": "HIGH"
    }
  ],
  "count": 1
}
```

**Install Tools:**
```bash
# Python
pip install safety pip-audit

# JavaScript
npm audit  # Built into npm
```

### Code Security Scanning (SAST)

Perform static application security testing:

```python
# Scan entire project
scan_code_security(".")

# Scan specific file or directory
scan_code_security("src/api")
scan_code_security("app.py", tool="bandit")
```

**Tools Used:**
- `bandit` - Python security linter
- `semgrep` - Multi-language static analysis

**Output:**
```json
{
  "scanned": "src/api",
  "tools": ["bandit", "semgrep"],
  "findings": [
    {
      "filename": "src/api/auth.py",
      "line_number": 45,
      "issue_text": "Possible SQL injection vector",
      "severity": "HIGH",
      "confidence": "HIGH"
    }
  ],
  "count": 1,
  "by_severity": {
    "HIGH": 1,
    "MEDIUM": 3,
    "LOW": 5
  }
}
```

**Install Tools:**
```bash
pip install bandit semgrep
```

### Secret Detection

Scan for accidentally committed secrets:

```python
# Scan entire repository
detect_secrets(".")

# Scan specific directory
detect_secrets("src")
```

**Tool Used:** `detect-secrets`

**Output:**
```json
{
  "scanned": ".",
  "tool": "detect-secrets",
  "secrets_found": 3,
  "files_with_secrets": 2,
  "by_file": {
    "config/database.py": 1,
    ".env.example": 2
  }
}
```

**Detects:**
- API keys
- Passwords
- Private keys
- AWS credentials
- Database connection strings
- JWT tokens

**Install Tool:**
```bash
pip install detect-secrets
```

### License Compliance

Check dependency licenses for compliance issues:

```python
check_license_compliance(".")
```

**Output:**
```json
{
  "language": "python",
  "tool": "pip-licenses",
  "total_packages": 45,
  "compliance_issues": [
    {
      "package": "some-library",
      "license": "GPL-3.0",
      "issue": "Restrictive license"
    }
  ],
  "issue_count": 1
}
```

**Flags These Licenses:**
- GPL-3.0 (requires source disclosure)
- AGPL-3.0 (network copyleft)
- GPL-2.0 (requires source disclosure)

**Install Tools:**
```bash
# Python
pip install pip-licenses

# JavaScript
npm install license-checker
```

## Usage Examples

### Example 1: Convert Config Files

```bash
# Convert Kubernetes YAML to JSON for processing
 rev "Convert k8s-deployment.yaml to JSON format"

# Result: k8s-deployment.json created
```

### Example 2: Clean Up Code

```bash
# Remove unused imports from all Python files
 rev "Remove unused imports from all files in src/ directory"

# Find and extract magic numbers to constants
 rev "Analyze src/config.py and suggest constant extraction"
```

### Example 3: Dependency Audit

```bash
# Complete dependency audit
 rev "Analyze dependencies, check for vulnerabilities, and suggest updates"

# Steps performed:
# 1. analyze_dependencies() - Check for issues
# 2. scan_dependencies_vulnerabilities() - Security check
# 3. update_dependencies() - Find outdated packages
```

### Example 4: Security Scan

```bash
# Comprehensive security audit
 rev "Perform complete security audit: scan code, check dependencies, detect secrets"

# Steps performed:
# 1. scan_code_security(".") - SAST analysis
# 2. scan_dependencies_vulnerabilities() - Dependency check
# 3. detect_secrets(".") - Secret detection
# 4. check_license_compliance() - License audit
```

### Example 5: Pre-Commit Checks

```bash
# Before committing
 rev "Remove unused imports, scan for secrets, and check dependencies"

# Safe commit workflow
 rev "Scan staged files for security issues and secrets"
```

## Integration with CI/CD

### GitHub Actions

```yaml
# .github/workflows/utilities.yml
name: Code Quality and Security

on: [push, pull_request]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup
        run: |
          pip install -r requirements.txt
          pip install bandit safety pip-licenses detect-secrets

      - name: Run security scan
        run: |
           rev "Run security scan and dependency audit"

      - name: Check for secrets
        run: |
           rev "Scan for accidentally committed secrets"
```

### GitLab CI

```yaml
# .gitlab-ci.yml
security:scan:
  stage: test
  script:
    - pip install bandit safety detect-secrets
     - rev "Perform comprehensive security audit"
  artifacts:
    reports:
      sast: security-report.json
```

## Best Practices

### File Conversion
1. **Backup originals** before converting
2. **Validate output** after conversion
3. **Use version control** to track changes
4. **Test with sample data** first

### Code Refactoring
1. **Run tests** before and after refactoring
2. **Review suggestions** before applying
3. **Refactor incrementally** (small changes)
4. **Commit frequently** during refactoring

### Dependency Management
1. **Pin versions** in production (==)
2. **Use virtual environments** always
3. **Update regularly** but test thoroughly
4. **Document breaking changes**

### Security Scanning
1. **Scan before every commit**
2. **Fix HIGH severity** issues immediately
3. **Review false positives** carefully
4. **Keep scanning tools updated**
5. **Never commit secrets** (use .gitignore)

## Troubleshooting

### "Tool not installed" Errors

Install the required tool:

```bash
# File conversion
pip install pyyaml

# Code refactoring
pip install autoflake

# Security scanning
pip install bandit semgrep safety pip-audit detect-secrets pip-licenses

# All at once
pip install pyyaml autoflake bandit semgrep safety pip-audit detect-secrets pip-licenses
```

### False Positives in Security Scans

Add exclusions or configure tools:

```bash
# Bandit: Use .bandit config file
# Create .bandit:
[bandit]
exclude_dirs = ['/test', '/tests']
skips = ['B101']  # Skip assert_used check

# detect-secrets: Generate baseline
detect-secrets scan > .secrets.baseline
```

### License Compliance Issues

Review and document exceptions:

```bash
# Generate full license report
pip-licenses --format=markdown > LICENSES.md

# Review GPL licenses case-by-case
# Some are LGPL (more permissive)
# Some are dual-licensed
```

## API Reference

### File Conversion

```python
convert_json_to_yaml(json_path: str, yaml_path: str = None) -> str
convert_yaml_to_json(yaml_path: str, json_path: str = None) -> str
convert_csv_to_json(csv_path: str, json_path: str = None) -> str
convert_json_to_csv(json_path: str, csv_path: str = None) -> str
convert_env_to_json(env_path: str, json_path: str = None) -> str
```

### Code Refactoring

```python
remove_unused_imports(file_path: str, language: str = "python") -> str
extract_constants(file_path: str, threshold: int = 3) -> str
simplify_conditionals(file_path: str) -> str
```

### Dependency Management

```python
analyze_dependencies(language: str = "auto") -> str
check_dependency_updates(language: str = "auto") -> str
check_dependency_vulnerabilities(language: str = "auto") -> str
# Legacy aliases:
update_dependencies(language: str = "auto", major: bool = False) -> str
scan_dependencies_vulnerabilities(language: str = "auto") -> str
```

### Security Scanning

```python
scan_code_security(path: str = ".", tool: str = "auto") -> str
detect_secrets(path: str = ".") -> str
check_license_compliance(path: str = ".") -> str
scan_security_issues(paths: list[str] | None = None, severity_threshold: str = "MEDIUM") -> str
check_contracts(paths: list[str] | None = None, timeout_seconds: int = 60) -> str
```

### Linting, Types, and Tests

```python
run_linters(paths: list[str] | None = None) -> str
run_type_checks(paths: list[str] | None = None) -> str
run_property_tests(test_paths: list[str] | None = None, max_examples: int = 200) -> str
generate_property_tests(targets: list[str], max_examples: int = 200) -> str
detect_flaky_tests(pattern: str | None = None, runs: int = 5) -> str
bisect_test_failure(test_command: str, good_ref: str, bad_ref: str = "HEAD") -> str
generate_repro_case(context: str, target_path: str = "tests/regressions/test_repro_case.py") -> str
compare_behavior_with_baseline(baseline_ref: str = "origin/main", test_selector: str | None = None) -> str
```

### Runtime, CI, and Migrations

```python
analyze_runtime_logs(log_paths: list[str], since: str | None = None) -> str
analyze_error_traces(log_paths: list[str], max_traces: int = 200) -> str
analyze_performance_regression(benchmark_cmd: str, baseline_file: str = ".rev-metrics/perf-baseline.json", tolerance_pct: float = 10.0) -> str
validate_ci_config(paths: list[str] | None = None) -> str
verify_migrations(path: str = "migrations") -> str
```

## Next Steps

- See [examples/scenarios/](examples/scenarios/) for usage examples
- See [ADVANCED_PLANNING.md](ADVANCED_PLANNING.md) for risk assessment
- See [examples/ci-cd/](examples/ci-cd/) for CI/CD integration

## License

Same as rev - MIT License
