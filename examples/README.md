# rev.py Examples

This directory contains comprehensive examples, templates, and CI/CD integrations for rev.py.

## Directory Structure

```
examples/
├── scenarios/          # Real-world usage scenarios
├── workflows/          # Common development workflow templates
└── ci-cd/             # CI/CD pipeline integrations
    ├── github-actions/ # GitHub Actions examples
    └── gitlab-ci/      # GitLab CI examples
```

## Quick Start

### 1. Real-World Scenarios

Learn how to use rev.py for common development tasks:

- **[Bug Fixing](scenarios/bug-fixing.md)** - Fix bugs with test-driven development
- **[Feature Development](scenarios/feature-development.md)** - Add new features iteratively
- **[Code Refactoring](scenarios/refactoring.md)** - Safely refactor code with tests
- **[Testing](scenarios/testing.md)** - Add comprehensive test coverage
- **[Documentation](scenarios/documentation.md)** - Generate and update documentation
- **[Code Review](scenarios/code-review.md)** - Automated code review and linting

### 2. Workflow Templates

Ready-to-use templates for common tasks:

- **[Python Development](workflows/python-development.md)** - Python project workflows
- **[JavaScript/Node.js](workflows/javascript-nodejs.md)** - JS/TS project workflows
- **[Database Migrations](workflows/database-migrations.md)** - Database schema changes
- **[API Development](workflows/api-development.md)** - REST/GraphQL API workflows
- **[Security Fixes](workflows/security-fixes.md)** - Patch security vulnerabilities
- **[Performance Optimization](workflows/performance.md)** - Optimize code performance

### 3. CI/CD Integration

Integrate rev.py into your CI/CD pipelines:

#### GitHub Actions
- **[Automated Code Review](.github/workflows/review.yml)** - Review PRs automatically
- **[Auto-Fix Linting](ci-cd/github-actions/auto-fix-linting.yml)** - Fix linting issues
- **[Test Coverage](ci-cd/github-actions/test-coverage.yml)** - Improve test coverage
- **[Security Scanning](ci-cd/github-actions/security-scan.yml)** - Fix security issues
- **[Documentation](ci-cd/github-actions/docs-update.yml)** - Auto-update docs

#### GitLab CI
- **[Pipeline Integration](ci-cd/gitlab-ci/.gitlab-ci.yml)** - Complete GitLab CI setup
- **[Code Quality](ci-cd/gitlab-ci/code-quality.yml)** - Quality checks and fixes
- **[Security Pipeline](ci-cd/gitlab-ci/security.yml)** - Security scanning
- **[Auto-Deployment](ci-cd/gitlab-ci/auto-deploy.yml)** - Deploy with rev.py

## Usage Examples

### Interactive REPL Mode

```bash
# Start interactive session
python rev.py --repl

agent> Review the authentication module
agent> Add input validation to all user endpoints
agent> Run tests and fix any failures
agent> /status
agent> /exit
```

### One-Shot Commands

```bash
# Quick fixes
python rev.py "Fix all ESLint errors"

# Feature development
python rev.py "Add rate limiting to API endpoints"

# Refactoring
python rev.py "Extract database logic into repository pattern"

# Testing
python rev.py "Add unit tests for the user service"
```

### Parallel Execution

```bash
# Run multiple tasks concurrently
python rev.py -j 4 "Review all API endpoints and add tests"

# Sequential for dependencies
python rev.py -j 1 "Refactor auth, update tests, then update docs"
```

## Best Practices

### 1. Start Small
Begin with simple, focused tasks before tackling complex refactoring:
```bash
# Good: Specific and focused
python rev.py "Add null check to getUserById function"

# Bad: Too broad
python rev.py "Fix everything"
```

### 2. Use Appropriate Models
Match model size to task complexity:
```bash
# Simple tasks (fast)
python rev.py --model llama3.1:8b "Fix typo in README"

# Complex refactoring (powerful)
python rev.py --model qwen3-coder:480b-cloud "Refactor auth system"
```

### 3. Review Changes
Always review changes before committing:
```bash
python rev.py "Add feature X"
git diff           # Review changes
git add .
git commit -m "Add feature X"
```

### 4. Leverage Parallel Execution
Use parallelism for independent tasks:
```bash
# Review multiple files in parallel
python rev.py -j 4 "Review all components and add JSDoc comments"

# Sequential when order matters
python rev.py -j 1 "Fix bug, add test, update docs"
```

## Environment Setup

### Local Development
```bash
# Install Ollama
brew install ollama  # macOS
curl -fsSL https://ollama.ai/install.sh | sh  # Linux

# Pull a model
ollama pull llama3.1:latest

# Install dependencies
pip install -r requirements.txt
```

### Cloud Models
```bash
# Use powerful cloud models
python rev.py --model qwen3-coder:480b-cloud "Complex task"

# Authenticate (first use only)
# Follow the URL provided and sign in
```

## Troubleshooting

### Common Issues

**Ollama connection errors:**
```bash
# Start Ollama service
ollama serve
```

**Model not found:**
```bash
# Pull the model first
ollama pull llama3.1:latest
```

**Task not completing:**
```bash
# Use a more powerful model
python rev.py --model llama3.1:70b "Complex task"

# Or be more specific
python rev.py "Add error handling to getUserById in src/services/user.js"
```

**Cloud model authentication:**
```bash
# Visit the URL shown and sign in
# Press Enter after authenticating
```

## Contributing

Have a useful example or workflow? Contributions are welcome!

1. Add your example to the appropriate directory
2. Update this README
3. Submit a pull request

## Support

- **Documentation**: See main [README.md](../README.md)
- **Issues**: Report at https://github.com/your-org/rev/issues
- **Questions**: Start a discussion

## License

MIT - Same as rev.py
