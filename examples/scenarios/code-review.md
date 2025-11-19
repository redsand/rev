# Code Review with rev.py

Automate code review tasks and improve code quality.

## Scenario 1: Pre-Commit Review

### Task
Review changes before committing.

### Command
```bash
python rev.py "Review uncommitted changes and suggest improvements"
```

### Review Output
```
Reviewing uncommitted changes...

✓ src/auth/login.py:
  - Good: Input validation added
  - Good: Error handling implemented
  - Suggestion: Consider rate limiting to prevent brute force

⚠ src/services/user_service.py:
  - Issue: N+1 query detected at line 45
    Recommendation: Use joinedload() to fetch related data
  - Issue: No input validation for email
    Recommendation: Add email format validation

✗ src/api/posts.py:
  - Critical: SQL injection vulnerability at line 23
    Fix: Use parameterized queries instead of string formatting
  - Critical: Missing authentication check
    Fix: Add @require_auth decorator

Summary:
  Files reviewed: 3
  Issues found: 5 (2 critical, 1 warning, 2 suggestions)
  Estimated fix time: 15 minutes
```

## Scenario 2: Pull Request Review

### Task
Automated PR review and comments.

### Command
```bash
python rev.py "Review pull request changes and create review comments"
```

### Generated Review
```markdown
## Code Review

### Overview
This PR adds user profile editing functionality. Overall structure is good,
but there are some security and performance concerns.

### Security Issues 🔴

**src/api/users.py:67**
```python
# Current code
sql = f"UPDATE users SET bio='{bio}' WHERE id={user_id}"
```
❌ SQL injection vulnerability. Use parameterized queries:
```python
# Suggested fix
db.execute("UPDATE users SET bio=? WHERE id=?", (bio, user_id))
```

### Performance Issues ⚠️

**src/services/user.py:34**
```python
for user in users:
    user.posts = Post.query.filter_by(user_id=user.id).all()
```
⚠️ N+1 query problem. Consider using join:
```python
users = User.query.options(joinedload(User.posts)).all()
```

### Code Quality 💡

**src/models/user.py:12**
- ✓ Good use of type hints
- ✓ Proper error handling
- 💡 Consider extracting validation to separate function

**tests/test_user.py:45**
- ✓ Good test coverage (85%)
- 💡 Add edge case tests for empty bio

### Recommendations

1. Fix SQL injection vulnerability (required)
2. Optimize N+1 queries (recommended)
3. Add input validation (recommended)
4. Increase test coverage to 90% (optional)

### Approval Status
❌ Requesting changes - security issues must be addressed
```

## Scenario 3: Code Smell Detection

### Task
Identify code smells and anti-patterns.

### Command
```bash
python rev.py "Analyze codebase for code smells and suggest refactoring"
```

### Detected Issues
```
Code Smell Analysis Report

1. Duplicate Code (10 instances)
   Location: src/api/*.py
   Description: Error handling code repeated across endpoints
   Suggestion: Extract to decorator

   Example locations:
   - src/api/users.py:23-30
   - src/api/posts.py:45-52
   - src/api/comments.py:12-19

   Suggested refactoring:
   ```python
   def handle_errors(f):
       @wraps(f)
       def wrapper(*args, **kwargs):
           try:
               return f(*args, **kwargs)
           except Exception as e:
               logger.error(f'Error: {e}')
               return {'error': str(e)}, 500
       return wrapper
   ```

2. Long Method (5 instances)
   Location: src/services/order.py:45
   Description: create_order() is 150 lines long
   Suggestion: Extract into smaller methods

   Suggested breakdown:
   - validate_order_data()
   - calculate_totals()
   - process_payment()
   - create_order_record()
   - send_confirmations()

3. God Object (1 instance)
   Location: src/models/user.py
   Description: User class has too many responsibilities
   Suggestion: Extract auth logic to AuthService

4. Magic Numbers (15 instances)
   Location: Various files
   Description: Hard-coded numbers without explanation
   Examples:
   - src/api/users.py:23 -> page_size = 20
   - src/services/auth.py:45 -> token_expiry = 3600

   Suggestion: Use named constants:
   ```python
   DEFAULT_PAGE_SIZE = 20
   TOKEN_EXPIRY_SECONDS = 3600
   ```

5. Deep Nesting (3 instances)
   Location: src/services/payment.py:67
   Description: 5 levels of nesting
   Suggestion: Use early returns or extract methods
```

## Scenario 4: Security Audit

### Task
Scan for security vulnerabilities.

### Command
```bash
python rev.py "Perform security audit and identify vulnerabilities"
```

### Security Report
```
Security Audit Report

🔴 CRITICAL (3 issues)

1. SQL Injection
   File: src/api/search.py:34
   Code: db.execute(f"SELECT * FROM users WHERE name='{query}'")
   Risk: Attacker can execute arbitrary SQL
   Fix: Use parameterized queries

2. Hardcoded Secrets
   File: src/config.py:12
   Code: SECRET_KEY = "my-secret-key-123"
   Risk: Secrets committed to version control
   Fix: Use environment variables

3. Missing Authentication
   File: src/api/admin.py:23
   Code: @app.route('/admin/users')
   Risk: Admin endpoints accessible without auth
   Fix: Add authentication middleware

⚠️ HIGH (5 issues)

4. Weak Password Requirements
   File: src/services/auth.py:56
   Risk: Passwords with only 6 characters allowed
   Fix: Require min 8 chars, mixed case, numbers

5. No Rate Limiting
   File: src/api/auth.py
   Risk: Vulnerable to brute force attacks
   Fix: Add rate limiting middleware

🟡 MEDIUM (8 issues)

6. CORS Misconfiguration
   File: src/app.py:15
   Code: CORS(app, origins='*')
   Risk: Allows requests from any origin
   Fix: Specify allowed origins explicitly

Summary:
  Critical: 3
  High: 5
  Medium: 8
  Total: 16 security issues found
```

## Scenario 5: Performance Analysis

### Task
Identify performance bottlenecks.

### Command
```bash
python rev.py "Analyze code for performance issues and suggest optimizations"
```

### Performance Report
```
Performance Analysis

⚠️ Critical Performance Issues

1. N+1 Query Problem
   Location: src/api/users.py:45
   Impact: 100+ database queries for 100 users
   Current: 2.3s response time
   Optimized: <0.2s (estimated)

   Fix:
   ```python
   # Before
   users = User.query.all()
   for user in users:
       user.posts  # Triggers query

   # After
   users = User.query.options(joinedload(User.posts)).all()
   ```

2. Missing Database Indexes
   Location: Database schema
   Impact: Full table scans on large tables
   Tables affected:
   - users.email (frequent WHERE clause)
   - posts.created_at (frequent ORDER BY)
   - posts.user_id (frequent JOIN)

   Fix:
   ```sql
   CREATE INDEX idx_users_email ON users(email);
   CREATE INDEX idx_posts_created_at ON posts(created_at DESC);
   CREATE INDEX idx_posts_user_id ON posts(user_id);
   ```

3. Inefficient Algorithm
   Location: src/utils/recommendations.py:67
   Impact: O(n²) complexity for large datasets
   Current: 5s for 1000 items
   Optimized: 0.5s (estimated)

   Fix: Use set intersection instead of nested loops

💡 Optimization Opportunities

4. Missing Caching
   Location: src/api/posts.py:23
   Suggestion: Cache frequently accessed posts
   Estimated improvement: 50% faster

5. Large Payload Size
   Location: src/api/users.py:34
   Issue: Returning all user fields (including password_hash)
   Fix: Use DTO to return only necessary fields
```

## Scenario 6: Style and Standards

### Task
Ensure code follows style guidelines.

### Command
```bash
python rev.py "Check code against PEP 8 style guide and fix violations"
```

### Style Report
```
Style Check Report (PEP 8)

src/api/users.py:
  Line 23: E501 line too long (92 > 79 characters)
  Line 45: E302 expected 2 blank lines, found 1
  Line 67: W291 trailing whitespace

src/services/auth.py:
  Line 12: E303 too many blank lines (3)
  Line 34: E261 at least two spaces before inline comment

src/models/user.py:
  Line 5: E401 multiple imports on one line
  Line 23: W293 blank line contains whitespace

Auto-fixing violations...

✓ Fixed 12/15 violations
⚠ Manual review needed for 3 violations

Remaining issues:
  src/api/users.py:23 - Line too long (needs manual refactoring)
  src/services/auth.py:34 - Comment placement (manual review)
  src/models/user.py:5 - Import order (manual review)
```

## Best Practices

### 1. Review Early and Often
```bash
# Before committing
python rev.py "Review uncommitted changes"

# Before pushing
python rev.py "Review changes since last push"
```

### 2. Automated PR Reviews
```yaml
# .github/workflows/review.yml
- name: Auto Review
  run: python rev.py "Review PR changes and comment"
```

### 3. Focus Areas
```bash
# Security focused
python rev.py "Security review focusing on auth and data access"

# Performance focused
python rev.py "Performance review focusing on database queries"
```

### 4. Use Review Checklists
```bash
python rev.py "Review against checklist: security, performance, tests, docs"
```

## Review Checklist

- [ ] Code follows style guidelines
- [ ] No security vulnerabilities
- [ ] Proper error handling
- [ ] Input validation implemented
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No performance issues
- [ ] No code smells

## Next Steps

- **[Bug Fixing](bug-fixing.md)** - Fix issues found in review
- **[Refactoring](refactoring.md)** - Address code smells
- **[Testing](testing.md)** - Add missing tests
- **[CI/CD Integration](../ci-cd/)** - Automate reviews
