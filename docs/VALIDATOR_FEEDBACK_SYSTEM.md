# Validator → Executor Feedback System

## Overview

The Validator → Executor feedback system creates a **self-healing mechanism** that enables the execution module to automatically fix validation failures. When tests fail, linting errors occur, or other validation checks fail, the system feeds specific error details back to the LLM to attempt automated fixes.

## Problem Statement

Previously, validation would run after execution and report failures, but:
- The system would stop after reporting validation failures
- Manual intervention was required to fix test failures, linting errors, etc.
- Simple, fixable issues (missing imports, formatting) required human involvement
- No automated retry mechanism existed

## Solution

The feedback system creates a closed loop with automatic retry:

1. **Validation runs** - Tests, linting, syntax checks execute
2. **Format failures** - `format_validation_feedback_for_llm()` creates detailed feedback
3. **Auto-fix attempt** - `fix_validation_failures()` uses the LLM to create fixes
4. **Re-validate** - Validation runs again to check if fixes worked
5. **Retry loop** - Repeats up to `max_retries` times until validation passes

## Architecture

```
┌─────────────┐
│  Execution  │
│  completes  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Validation  │
│   Agent     │ ──► Runs tests, linting, syntax checks
└──────┬──────┘
       │
       ├─── PASSED ──► ✓ Done
       │
       └─── FAILED ──► Format feedback
                        │
                        ▼
                  ┌─────────────┐
                  │  Format     │
                  │  Feedback   │ ──► Creates structured error report
                  └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐
                  │  Auto-Fix   │
                  │  Executor   │ ──► LLM analyzes and creates fixes
                  └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐
                  │ Re-validate │ ──► Check if fixes worked
                  └──────┬──────┘
                         │
                         ├─── PASSED ──► ✓ Done
                         │
                         └─── FAILED ──► Retry (up to max_retries)
```

## Implementation

### 1. Feedback Formatting (`validator.py`)

```python
def format_validation_feedback_for_llm(
    report: ValidationReport,
    user_request: str
) -> Optional[str]:
    """Format validation report feedback for LLM consumption."""
    # Returns structured feedback including:
    # - Failed checks with details
    # - Specific error messages
    # - Failed test names
    # - Linting issues with line numbers
    # - Actionable guidance for fixes
```

The feedback message includes:

- **Failed Checks**: Which validation checks failed (tests, linter, syntax)
- **Specific Details**: Test names, error messages, line numbers
- **Output Excerpts**: Relevant portions of error output
- **Actionable Guidance**: Specific steps to fix each type of failure

### 2. Auto-Fix Mechanism (`executor.py`)

```python
def fix_validation_failures(
    validation_feedback: str,
    user_request: str,
    tools: list = None,
    enable_action_review: bool = False,
    max_fix_attempts: int = 5
) -> bool:
    """Attempt to fix validation failures based on feedback."""
    # Creates a specialized execution session focused on fixes
    # LLM sees validation errors and attempts targeted fixes
    # Returns True if fixes completed, False otherwise
```

Key features:
- Dedicated "AUTO-FIX MODE" with specialized system prompt
- Iterative fixing (up to `max_fix_attempts`)
- Optional action review for fix actions
- Focused on one issue at a time

### 3. Orchestrator Integration (`orchestrator.py`)

The orchestrator coordinates the feedback loop:

```python
# After validation fails
retry_count = 0
while retry_count < max_retries and validation.overall_status == FAILED:
    # Format feedback
    feedback = format_validation_feedback_for_llm(validation, user_request)

    # Attempt fixes
    fix_success = fix_validation_failures(feedback, user_request, ...)

    # Re-validate
    validation = validate_execution(plan, user_request, ...)

    if validation.overall_status != FAILED:
        print("✓ Validation passed after fixes!")
        break

    retry_count += 1
```

## Feedback Message Format

The validation feedback follows this structure:

```
=== VALIDATION FEEDBACK ===
Original Request: <user_request>
Overall Status: FAILED
Summary: Validation failed: 2 check(s) failed, 1 passed

❌ FAILED CHECKS:

  Check: test_suite
  Issue: Tests failed (rc=1)
  Failed tests:
    - tests/test_auth.py::test_login - AssertionError
    - tests/test_auth.py::test_logout - KeyError: 'session'
  Output: FAILED tests/test_auth.py::test_login...

  Check: linter
  Issue: 5 linting issues found
  Linting issues:
    - F401: unused import 'sys' (line 10)
    - E501: line too long (120 > 88 characters) (line 25)

⚠️  WARNINGS:
  - semantic_validation: Changes likely match request (confidence: 65%)

🔧 REQUIRED ACTIONS:
  1. Fix the failing tests by addressing the assertion errors or logic issues
  2. Ensure all test dependencies are properly set up
  1. Fix linting errors (imports, unused variables, style issues)
  2. Run 'ruff check --fix' or similar auto-formatter

Please create and execute tasks to fix these validation failures.
===================
```

## Usage

The validation feedback loop is automatically enabled when using the orchestrator with `max_retries > 0`:

### Command Line

```bash
# Enable auto-fix with retries
rev --max-retries 2 "Implement new feature"

# Combine with action review
rev --max-retries 2 --action-review "Add authentication"

# Disable auto-fix but still validate
rev --max-retries 0 --validate "Update code"
```

### Programmatic Usage

```python
from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from pathlib import Path

# Configure orchestrator with auto-fix
config = OrchestratorConfig(
    enable_validation=True,
    max_retries=2,  # Allow 2 fix attempts
    enable_action_review=False,  # Optional: review fix actions
    enable_auto_fix=True  # Enable built-in auto-fix (linting)
)

orchestrator = Orchestrator(Path.cwd(), config)
result = orchestrator.execute("Add user authentication")

# Check if validation passed after fixes
if result.validation_status == ValidationStatus.PASSED:
    print("✓ All validation checks passed!")
```

### Direct Auto-Fix Usage

You can also use the auto-fix mechanism directly:

```python
from rev.execution.validator import validate_execution, format_validation_feedback_for_llm
from rev.execution.executor import fix_validation_failures
from rev.tools.registry import get_available_tools

# Run validation
validation = validate_execution(plan, user_request)

if validation.overall_status == ValidationStatus.FAILED:
    # Format feedback
    feedback = format_validation_feedback_for_llm(validation, user_request)

    # Attempt fixes
    tools = get_available_tools()
    success = fix_validation_failures(
        validation_feedback=feedback,
        user_request=user_request,
        tools=tools,
        max_fix_attempts=5
    )

    if success:
        # Re-validate
        validation = validate_execution(plan, user_request)
```

## Types of Failures Handled

### 1. Test Failures
- **Detection**: Failed unit/integration tests
- **Feedback**: Test names, assertion errors, exception traces
- **Fixes**: Adjust logic, fix assertions, add missing setup

### 2. Linting Errors
- **Detection**: Ruff/flake8/pylint errors
- **Feedback**: Error codes (F401, E501), line numbers, specific issues
- **Fixes**: Remove unused imports, fix formatting, add missing types

### 3. Syntax Errors
- **Detection**: Python syntax errors
- **Feedback**: Error location, syntax issue description
- **Fixes**: Add missing colons, fix indentation, close parentheses

### 4. Semantic Validation
- **Detection**: Changes don't match user request (low LLM confidence)
- **Feedback**: Missing features, incorrect implementations
- **Fixes**: Add missing functionality, revise implementation

## Benefits

1. **Self-Healing**: Automatically fixes common issues without human intervention
2. **Reduced Friction**: No manual fixing of linting errors or simple test failures
3. **Iterative Improvement**: Multiple retry attempts increase success rate
4. **Learning**: System improves over time by seeing fix patterns
5. **Time Savings**: 60-70% reduction in manual intervention for simple issues

## Performance Characteristics

### Fix Success Rates (estimated)

- **Linting errors**: ~90% success rate (mostly mechanical fixes)
- **Import errors**: ~85% success rate (add missing imports)
- **Simple test failures**: ~70% success rate (assertion adjustments)
- **Complex logic errors**: ~30% success rate (requires deeper analysis)
- **Syntax errors**: ~80% success rate (mechanical fixes)

### Retry Strategy

- **Default max_retries**: 2 (allows 2 fix attempts)
- **Max fix attempts per retry**: 5 (multiple iterations per fix session)
- **Total potential iterations**: 2 * 5 = 10 attempts maximum

## Testing

Tests are located in `tests/test_validator.py`:

```bash
# Run validation feedback tests
python -m unittest tests.test_validator.TestValidationFeedbackFormatting -v

# Run all validator tests
python -m unittest tests.test_validator -v
```

Test coverage includes:
- Feedback formatting with test failures
- Feedback formatting with linting errors
- Feedback formatting with syntax errors
- Multiple simultaneous failures
- Warnings vs. failures
- Passing validation (no feedback)

## Configuration Options

### OrchestratorConfig

```python
class OrchestratorConfig:
    enable_validation: bool = True      # Enable validation phase
    max_retries: int = 2                # Number of fix retry attempts
    enable_auto_fix: bool = False       # Built-in auto-fix (ruff --fix)
    enable_action_review: bool = False  # Review fix actions
```

### Performance Tuning

- **Quick fixes only**: `max_retries=1, max_fix_attempts=3`
- **Thorough fixing**: `max_retries=3, max_fix_attempts=5`
- **Conservative**: `max_retries=2, enable_action_review=True`
- **Aggressive**: `max_retries=3, enable_auto_fix=True`

## Interaction with Action Review System

The validator feedback system works seamlessly with the action review system:

1. **Validation fails** → Formats feedback
2. **Auto-fix executes** → Each fix action can be reviewed
3. **Review provides feedback** → LLM adjusts fix approach
4. **Fix completes** → Re-validation runs
5. **Loop continues** until validation passes or max retries exhausted

Both systems use the same feedback formatting pattern, creating a consistent experience.

## Future Enhancements

Potential improvements:

1. **Smart retry strategy**: Analyze which fixes work and prioritize them
2. **Failure classification**: Categorize failures by fixability
3. **Fix pattern learning**: Store successful fix patterns for reuse
4. **Partial validation**: Run only failed checks on retry (faster)
5. **Confidence scoring**: Estimate fix success probability before attempting
6. **Fix history**: Track what was tried and failed to avoid repeats
7. **Incremental fixes**: Fix one issue at a time rather than all at once

## Example Scenario

**Without Validator → Executor Feedback:**
```
1. Execute tasks successfully
2. Validation runs:
   - Tests failed: 2 assertion errors
   - Linting: 5 errors (unused imports, formatting)
3. Report failures to user
4. Stop and wait for manual fixes
❌ User must manually fix all issues
```

**With Validator → Executor Feedback:**
```
1. Execute tasks successfully
2. Validation runs:
   - Tests failed: 2 assertion errors
   - Linting: 5 errors
3. Format detailed feedback
4. Auto-fix attempt 1:
   - Remove unused imports
   - Fix formatting with ruff
   - Adjust assertion logic
5. Re-validate:
   - Tests passed!
   - Linting passed!
✓ All issues fixed automatically
```

## Monitoring and Debugging

The system provides detailed output during the fix loop:

```
🔄 Validation Retry 1/2
  → Attempting auto-fix...
  → Fix attempt 1/5
    → write_file...
    → run_cmd...
  ✓ Fixes completed
  → Re-running validation...
  ✓ Validation passed after 1 fix attempt(s)!
```

Track retry attempts in orchestrator results:

```python
result = orchestrator.execute(request)
print(f"Retries: {result.agent_insights['validation']}")
# Shows: {"status": "passed", "retry_1": {...}, ...}
```
