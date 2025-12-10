# rev Examples

This directory contains comprehensive examples, templates, and CI/CD integrations for rev.

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

Learn how to use rev for common development tasks:

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

Integrate rev into your CI/CD pipelines:

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
- **[Auto-Deployment](ci-cd/gitlab-ci/auto-deploy.yml)** - Deploy with rev

## Usage Examples

### 6-Agent System (v2.0.1)

rev now features a **6-agent autonomous system**:

| Agent | Purpose | Flag |
|-------|---------|------|
| Learning | Project memory across sessions | `--learn` |
| Research | Pre-planning codebase exploration | `--research` |
| Planning | Task breakdown | (always enabled) |
| Review | Plan/action validation | `--review` (default) |
| Execution | Task execution | (always enabled) |
| Validation | Post-execution checks | `--validate` (default) |

### Orchestrator Mode (Full Autonomy)

```bash
# Enable orchestrator to coordinate all agents
rev --orchestrate --learn --research "Implement user authentication"

# The orchestrator runs agents in sequence:
# 1. Learning → recalls similar past tasks
# 2. Research → explores codebase for context
# 3. Planning → creates execution plan
# 4. Review → validates plan
# 5. Execution → runs tasks
# 6. Validation → verifies results
# 7. Learning → stores patterns for future
```

### Interactive REPL Mode

```bash
# Start interactive session
rev --repl

agent> Review the authentication module
agent> Add input validation to all user endpoints
agent> Run tests and fix any failures
agent> /status
agent> /exit
```

### One-Shot Commands

```bash
# Quick fixes
rev "Fix all ESLint errors"

# Feature development with research
rev --research "Add rate limiting to API endpoints"

# Complex feature with full orchestration
rev --orchestrate "Build payment processing system"

# Refactoring with strict review
rev --review-strictness strict "Extract database logic into repository pattern"

# Testing with auto-fix
rev --auto-fix "Add unit tests for the user service"
```

### Agent-Specific Options

```bash
# Research agent options
rev --research "Find authentication code"
rev --research --research-depth deep "Analyze system architecture"
rev --research --research-depth shallow "Quick file search"

# Review agent options
rev --review-strictness strict "Database migration"
rev --review-strictness lenient "Update README"
rev --action-review "Sensitive security changes"
rev --no-review "Trivial typo fix"

# Validation agent options
rev --validate "Add new feature"  # default
rev --no-validate "Quick docs update"
rev --auto-fix "Add linting configuration"

# Learning agent
rev --learn "Add user preferences"
```

### Parallel Execution

```bash
# Run multiple tasks concurrently
rev -j 4 "Review all API endpoints and add tests"

# Sequential for dependencies
rev -j 1 "Refactor auth, update tests, then update docs"

# Parallel with orchestration
rev --orchestrate -j 4 "Implement multiple features"
```

## Best Practices

### 1. Start Small
Begin with simple, focused tasks before tackling complex refactoring:
```bash
# Good: Specific and focused
rev "Add null check to getUserById function"

# Bad: Too broad
rev "Fix everything"
```

### 2. Use Appropriate Models
Match model size to task complexity:
```bash
# Simple tasks (fast)
rev --model llama3.1:8b "Fix typo in README"

# Complex refactoring (powerful)
rev --model qwen3-coder:480b-cloud "Refactor auth system"
```

### 3. Review Changes
Always review changes before committing:
```bash
rev "Add feature X"
git diff           # Review changes
git add .
git commit -m "Add feature X"
```

### 4. Leverage Parallel Execution
Use parallelism for independent tasks:
```bash
# Review multiple files in parallel
rev -j 4 "Review all components and add JSDoc comments"

# Sequential when order matters
rev -j 1 "Fix bug, add test, update docs"
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
rev --model qwen3-coder:480b-cloud "Complex task"

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
rev --model llama3.1:70b "Complex task"

# Or be more specific
rev "Add error handling to getUserById in src/services/user.js"
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

MIT - Same as rev
