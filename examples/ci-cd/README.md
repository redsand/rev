# CI/CD Integration Examples

Integrate rev.py into your CI/CD pipelines for automated code improvements, testing, security scanning, and deployments.

## Available Integrations

### GitHub Actions

Located in `github-actions/`:

#### 1. Auto-Fix Linting (`auto-fix-linting.yml`)
Automatically fix linting errors and code style issues.

**Features:**
- Detects linting errors (ESLint, flake8, etc.)
- Uses rev.py to auto-fix issues
- Creates PR with fixes or commits directly
- Supports both Python and JavaScript projects

**Usage:**
```yaml
# Copy to .github/workflows/auto-fix-linting.yml
```

#### 2. Test Coverage (`test-coverage.yml`)
Improve test coverage automatically.

**Features:**
- Analyzes current test coverage
- Adds tests to reach target coverage (default 80%)
- Creates PR with new tests
- Weekly scheduled runs

**Usage:**
```yaml
# Copy to .github/workflows/test-coverage.yml
```

**Manual trigger:**
```bash
gh workflow run test-coverage.yml -f target_coverage=85
```

#### 3. Security Scanning (`security-scan.yml`)
Scan for and auto-fix security vulnerabilities.

**Features:**
- Runs Bandit, Safety, and pip-audit
- Auto-fixes code vulnerabilities
- Updates vulnerable dependencies
- Creates security issues for critical findings
- Weekly scheduled scans

**Usage:**
```yaml
# Copy to .github/workflows/security-scan.yml
```

#### 4. Code Review (`code-review.yml`)
Automated code review for pull requests.

**Features:**
- Reviews code quality, security, and performance
- Posts detailed review comments
- Checks code complexity
- Approves or requests changes automatically

**Usage:**
```yaml
# Copy to .github/workflows/code-review.yml
```

#### 5. Documentation Update (`docs-update.yml`)
Auto-generate and update documentation.

**Features:**
- Generates API documentation
- Adds missing docstrings
- Updates README and examples
- Deploys to GitHub Pages
- Triggered on code changes

**Usage:**
```yaml
# Copy to .github/workflows/docs-update.yml
```

### GitLab CI

Located in `gitlab-ci/`:

#### 1. Main Pipeline (`.gitlab-ci.yml`)
Complete CI/CD pipeline with rev.py integration.

**Features:**
- Testing with coverage
- Code quality checks
- Security scanning
- Auto-fix capabilities
- Automated code review
- Deployment support

**Usage:**
```yaml
# Copy to .gitlab-ci.yml
```

#### 2. Code Quality (`code-quality.yml`)
Comprehensive code quality analysis and improvement.

**Features:**
- Complexity analysis
- Code smell detection
- Duplicate code removal
- Refactoring suggestions
- Quality dashboard

**Usage:**
```yaml
# Include in .gitlab-ci.yml:
include:
  - local: '.gitlab/ci/code-quality.yml'
```

#### 3. Security Pipeline (`security.yml`)
Advanced security scanning and remediation.

**Features:**
- SAST (Static Application Security Testing)
- Dependency vulnerability scanning
- Secret detection
- License compliance
- Auto-fix vulnerabilities
- Security reporting

**Usage:**
```yaml
# Include in .gitlab-ci.yml:
include:
  - local: '.gitlab/ci/security.yml'
```

#### 4. Auto-Deployment (`auto-deploy.yml`)
Automated deployment with health checks.

**Features:**
- Blue-green deployments
- Pre-deployment validation
- Smoke tests
- Health monitoring
- Automatic rollback
- Deployment reports

**Usage:**
```yaml
# Include in .gitlab-ci.yml:
include:
  - local: '.gitlab/ci/auto-deploy.yml'
```

## Setup Instructions

### GitHub Actions Setup

1. **Copy workflow files:**
```bash
cp examples/ci-cd/github-actions/*.yml .github/workflows/
```

2. **Configure secrets:**
```bash
# Add to repository secrets (Settings > Secrets)
# Optional: For Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

3. **Customize model (optional):**
```yaml
# Edit workflow files to use different model
- name: Install Ollama
  run: |
    ollama pull qwen3-coder:480b-cloud  # More powerful cloud model
```

4. **Enable workflows:**
- Go to Actions tab in your repository
- Enable the workflows you want to use

### GitLab CI Setup

1. **Copy pipeline files:**
```bash
cp examples/ci-cd/gitlab-ci/.gitlab-ci.yml .
mkdir -p .gitlab/ci
cp examples/ci-cd/gitlab-ci/*.yml .gitlab/ci/
```

2. **Configure variables:**
```yaml
# In GitLab: Settings > CI/CD > Variables
OLLAMA_MODEL=llama3.1:latest
KUBE_URL=https://kubernetes-cluster
KUBE_TOKEN=<your-token>
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

3. **Setup Ollama service:**
The pipeline uses Ollama as a GitLab CI service. Ensure your GitLab runner supports services.

4. **Enable specific pipelines:**
```yaml
# In .gitlab-ci.yml, include only what you need:
include:
  - local: '.gitlab/ci/code-quality.yml'
  - local: '.gitlab/ci/security.yml'
  # - local: '.gitlab/ci/auto-deploy.yml'  # Uncomment to enable
```

## Configuration Options

### Model Selection

**Local models (fast, free):**
```yaml
ollama pull llama3.1:8b  # Fast, good for simple tasks
ollama pull llama3.1:70b  # Powerful, for complex tasks
```

**Cloud models (powerful, requires auth):**
```yaml
ollama pull qwen3-coder:480b-cloud  # Most powerful
ollama pull llama3.3:90b-cloud
```

### Customizing Auto-Fix Behavior

**GitHub Actions:**
```yaml
# In workflow file
- name: Auto-fix with custom instructions
  run: |
    python rev.py "Fix linting errors following our team's style guide at docs/STYLE.md"
```

**GitLab CI:**
```yaml
# In .gitlab-ci.yml
fix:lint:
  script:
    - python rev.py "Fix linting issues using black and our custom rules"
```

### Adjusting Thresholds

**Test coverage:**
```yaml
# GitHub Actions
target_coverage: '85'  # Default is 80

# GitLab CI
variables:
  CODE_QUALITY_THRESHOLD: "85"
```

**Security severity:**
```yaml
# GitLab CI
variables:
  SECURITY_SEVERITY_THRESHOLD: "MEDIUM"  # Default is HIGH
```

## Common Use Cases

### 1. Lint on Every Commit
```yaml
# GitHub Actions
on:
  push:
    branches: [ main, develop ]

# GitLab CI
only:
  - main
  - develop
```

### 2. Weekly Security Scan
```yaml
# GitHub Actions
on:
  schedule:
    - cron: '0 0 * * 1'  # Every Monday

# GitLab CI
security:scan:
  only:
    - schedules
```

### 3. Coverage Improvement Sprint
```yaml
# Manually trigger coverage improvement
gh workflow run test-coverage.yml -f target_coverage=90

# Or in GitLab, trigger manually from UI
```

### 4. Pre-Deployment Checks
```yaml
# Run before deploying
deploy:
  needs:
    - test:unit
    - quality:lint
    - security:scan
  when: manual
```

## Troubleshooting

### Ollama Connection Issues

**GitHub Actions:**
```yaml
# Increase wait time
- name: Wait for Ollama
  run: |
    for i in {1..30}; do
      curl -s http://localhost:11434/api/tags && break
      sleep 2
    done
```

**GitLab CI:**
```yaml
# Use longer timeout
before_script:
  - until curl -s http://ollama:11434/api/tags; do
      sleep 5
    done
```

### Model Pull Failures

```yaml
# Use cached model or fallback
- curl -X POST http://ollama:11434/api/pull \
    -d '{"name": "llama3.1:latest"}' || \
  curl -X POST http://ollama:11434/api/pull \
    -d '{"name": "llama3.1:8b"}'
```

### Git Push Permissions

**GitHub Actions:**
```yaml
# Use GITHUB_TOKEN
- uses: actions/checkout@v4
  with:
    token: ${{ secrets.GITHUB_TOKEN }}
```

**GitLab CI:**
```yaml
# Use CI_JOB_TOKEN
- git push https://oauth2:$CI_JOB_TOKEN@$CI_SERVER_HOST/$CI_PROJECT_PATH.git
```

## Best Practices

1. **Start Simple**: Begin with linting and coverage, then add security and code review
2. **Use Manual Triggers**: For expensive operations (cloud models), use manual triggers
3. **Monitor Costs**: Track Ollama cloud model usage if using paid models
4. **Review Auto-Fixes**: Always review auto-generated fixes before merging
5. **Customize Prompts**: Tailor prompts to your team's standards and practices
6. **Set Appropriate Thresholds**: Don't aim for 100% coverage immediately

## Examples in Action

### Scenario: New Pull Request

1. **Auto code review** runs and posts comments
2. **Linting** detects issues and auto-fixes them
3. **Security scan** checks for vulnerabilities
4. **Coverage** check ensures new code is tested
5. **Documentation** is updated if needed

Result: High-quality, secure, tested code with minimal manual effort.

### Scenario: Security Vulnerability Discovered

1. **Weekly security scan** detects vulnerability
2. **Auto-fix** applies patch and updates dependencies
3. **Tests** verify the fix doesn't break anything
4. **MR/PR created** for review
5. **Team notified** via Slack/Email

Result: Fast response to security issues with automated remediation.

## Next Steps

- **[Scenarios](../scenarios/)** - See real-world usage examples
- **[Workflows](../workflows/)** - Language-specific workflow templates
- **Main [README](../../README.md)** - rev.py documentation

## Support

For issues or questions:
- Check troubleshooting section above
- Review workflow logs in your CI system
- Report issues at https://github.com/your-org/rev/issues
