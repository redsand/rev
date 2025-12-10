# Bug Fixing with rev

Learn how to efficiently fix bugs using rev's autonomous capabilities.

## Scenario 1: Fix a Specific Bug

### Problem
Users report that the login function crashes when email is null.

### Solution
```bash
rev "Fix null pointer error in login function when email is null"
```

### What rev does:
1. Searches for the login function
2. Identifies the bug
3. Adds null check
4. Runs tests to verify fix
5. Reports completion

### Example Output
```
Planning Phase:
  1. [REVIEW] Locate login function
  2. [REVIEW] Analyze the null pointer error
  3. [EDIT] Add null check for email parameter
  4. [TEST] Run authentication tests
  5. [TEST] Verify fix with edge cases

Execution Phase:
  ✓ Located login function in src/auth/login.js:45
  ✓ Found issue: email parameter not validated
  ✓ Added null check at line 47
  ✓ Tests passing (15/15)
  ✓ Fix verified

Summary:
  Files changed: 1
  Tests added: 0
  Tests passing: 15/15
```

## Scenario 2: Fix All Linting Errors

### Problem
CI pipeline fails due to 23 ESLint errors.

### Solution
```bash
# Run with parallel execution for speed
rev -j 4 "Fix all ESLint errors in src/ directory"
```

### Generated Plan
```
1. [REVIEW] Run ESLint to identify all errors
2. [EDIT] Fix unused variable warnings (8 files)
3. [EDIT] Fix import order issues (5 files)
4. [EDIT] Fix indentation errors (3 files)
5. [EDIT] Fix missing semicolons (7 files)
6. [TEST] Run ESLint again to verify all fixes
```

### Advanced: Auto-commit fixes
```bash
rev "Fix all ESLint errors"
git add .
git commit -m "Fix: Resolve all ESLint errors"
```

## Scenario 3: Test-Driven Bug Fix

### Problem
Bug report: "API returns 500 when user ID is invalid"

### Solution
```bash
rev "Add test for invalid user ID, then fix the bug to make test pass"
```

### What happens:
1. **Agent creates test first**
   ```python
   def test_invalid_user_id():
       response = client.get('/users/invalid')
       assert response.status_code == 404
       assert 'error' in response.json()
   ```

2. **Test fails (expected)**
   ```
   FAILED tests/test_api.py::test_invalid_user_id - 500 != 404
   ```

3. **Agent fixes the code**
   ```python
   @app.route('/users/<user_id>')
   def get_user(user_id):
       # Added validation
       if not user_id.isdigit():
           return jsonify({'error': 'Invalid user ID'}), 404

       user = db.get_user(int(user_id))
       # ... rest of code
   ```

4. **Test passes**
   ```
   ✓ tests/test_api.py::test_invalid_user_id PASSED
   ```

## Scenario 4: Fix Failing Tests

### Problem
After a refactoring, 5 tests are failing.

### Solution
```bash
rev "Run tests, analyze failures, and fix all failing tests"
```

### Process
```
Step 1: Running tests...
  ✗ test_user_creation FAILED
  ✗ test_user_update FAILED
  ✗ test_user_deletion FAILED
  ✗ test_user_authentication FAILED
  ✗ test_user_permissions FAILED

Step 2: Analyzing failures...
  Root cause: User model constructor changed signature

Step 3: Fixing tests...
  ✓ Updated test_user_creation - fixed constructor call
  ✓ Updated test_user_update - fixed constructor call
  ✓ Updated test_user_deletion - fixed constructor call
  ✓ Updated test_user_authentication - fixed constructor call
  ✓ Updated test_user_permissions - fixed constructor call

Step 4: Verifying fixes...
  ✓ All tests passing (25/25)
```

## Scenario 5: Debug Performance Issue

### Problem
API endpoint is slow (2+ seconds response time).

### Solution
```bash
rev "Profile the /users endpoint and fix performance issues"
```

### Agent actions:
1. **Adds profiling**
   ```python
   import cProfile
   import pstats

   profiler = cProfile.Profile()
   profiler.enable()
   # endpoint code
   profiler.disable()
   stats = pstats.Stats(profiler)
   stats.print_stats()
   ```

2. **Identifies bottleneck**
   ```
   Found: N+1 query problem
   Each user triggers 10+ database queries
   ```

3. **Fixes issue**
   ```python
   # Before: N+1 queries
   users = User.query.all()
   for user in users:
       user.posts  # Triggers query for each user

   # After: Single query with join
   users = User.query.options(
       joinedload(User.posts)
   ).all()
   ```

4. **Verifies improvement**
   ```
   Before: 2.3 seconds
   After: 0.15 seconds
   ✓ 15x performance improvement
   ```

## Scenario 6: Fix Security Vulnerability

### Problem
Security scanner found SQL injection vulnerability.

### Solution
```bash
rev "Fix SQL injection vulnerability in search function"
```

### Fix process:
```python
# Before (vulnerable)
def search_users(query):
    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
    return db.execute(sql)

# After (secure)
def search_users(query):
    sql = "SELECT * FROM users WHERE name LIKE ?"
    return db.execute(sql, (f'%{query}%',))
```

### Verification:
```python
# Agent adds security test
def test_sql_injection_prevented():
    malicious_input = "'; DROP TABLE users; --"
    result = search_users(malicious_input)
    # Should not execute DROP TABLE
    assert db.table_exists('users')
```

## Best Practices

### 1. Be Specific
```bash
# Good: Specific file and function
rev "Fix null check in getUserById in src/services/user.js"

# Less effective: Too vague
rev "Fix bugs"
```

### 2. Include Context
```bash
# Good: Includes error message
rev "Fix TypeError: Cannot read property 'name' of undefined in user profile page"

# Good: Includes test failure
rev "Fix test_user_creation - AssertionError: expected 201, got 500"
```

### 3. Request Tests
```bash
# Always verify fixes with tests
rev "Fix login bug and add test to prevent regression"
```

### 4. Use REPL for Investigation
```bash
rev --repl

agent> Show me the test failure details
agent> Find the function that's causing the error
agent> Fix the null pointer issue
agent> Run tests to verify
agent> /exit
```

## Common Bug Patterns

### Null/Undefined Checks
```bash
rev "Add null checks to all user input handling"
```

### Type Errors
```bash
rev "Fix type errors - ensure user.id is always a number"
```

### Race Conditions
```bash
rev "Fix race condition in async user creation"
```

### Memory Leaks
```bash
rev "Fix memory leak - ensure event listeners are cleaned up"
```

### Off-by-One Errors
```bash
rev "Fix off-by-one error in pagination logic"
```

## Integration with CI/CD

### Automatic Bug Fixes
```yaml
# .github/workflows/auto-fix.yml
name: Auto-Fix Bugs
on:
  issues:
    types: [labeled]

jobs:
  auto-fix:
    if: github.event.label.name == 'bug'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Fix bug
        run: |
          rev "Fix: ${{ github.event.issue.title }}"
          git config user.name "rev-bot"
          git commit -am "Auto-fix: ${{ github.event.issue.title }}"
          gh pr create --title "Fix: ${{ github.event.issue.title }}"
```

## Next Steps

- **[Feature Development](feature-development.md)** - Add new features
- **[Testing](testing.md)** - Improve test coverage
- **[Refactoring](refactoring.md)** - Refactor code safely
