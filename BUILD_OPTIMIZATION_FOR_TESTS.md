# Build Optimization for Test Fixes

## Summary

When fixing test failures, rev no longer runs unnecessary production build commands like `npm build` or `python setup.py build`. Tests now run immediately after fixes, improving iteration speed.

## Problem

Previously, when a test task failed with a syntax error, the diagnostic task builder would:
1. Create an edit task to fix the syntax error
2. Create a build task to compile/validate the code
3. Create a test task to re-run the tests

For test files, step 2 (the build) is unnecessary since:
- Tests aren't part of production builds
- Test files can be run directly without compilation in most setups
- This adds latency without value

## Solution

Modified `_build_diagnostic_tasks_for_failure()` in `rev/execution/orchestrator.py` (lines 2174-2187) to:

1. **Detect test-related failures** by checking:
   - `task.action_type == "test"` - The failed task was a test task
   - Test file path patterns:
     - `/test/` or `\\test` in path
     - `.test.ts`, `.test.js`, `.spec.ts`, `.spec.js` extensions
     - `_test.py`, `test_.py` patterns

2. **Skip build step** when fixing test files or test task failures

3. **Preserve build step** for source file fixes (non-test code)

## Code Change

```python
# Skip build for test-related tasks - run tests directly instead
is_test_task = task.action_type and task.action_type.lower() == "test"
is_test_file = target_path and (
    "/test" in target_path or "\\test" in target_path or
    target_path.endswith(".test.ts") or target_path.endswith(".test.js") or
    target_path.endswith(".spec.ts") or target_path.endswith(".spec.js") or
    target_path.endswith("_test.py") or target_path.endswith("test_.py")
)

if not (is_test_task or is_test_file):
    # Only run build for non-test code
    build_cmd = _detect_build_command_for_root(config.ROOT or Path.cwd())
    if build_cmd:
        tasks.append(Task(
            description=f"Run build to surface syntax errors and exact locations: {build_cmd}",
            action_type="run",
        ))
```

## Test Coverage

Created `tests/test_skip_build_for_test_fixes.py` with test cases:

1. **test_syntax_error_in_test_file_skips_build**
   - Syntax error in `tests/user.test.ts`
   - Result: 0 build tasks ✓

2. **test_syntax_error_in_source_file_includes_build**
   - Syntax error in `src/auth.ts`
   - Result: 1 build task ✓

3. **test_watch_mode_fix_skips_build**
   - Watch mode timeout with fix
   - Result: 0 build tasks ✓

4. **test_test_file_patterns_detected**
   - Tests various file patterns (`.test.ts`, `.spec.js`, `_test.py`, etc.)
   - All correctly skip build ✓

## Impact

### Before
```
Test fails → Fix syntax → Run build → Run test
                          (unnecessary for tests)
```

### After
```
Test fails → Fix syntax → Run test immediately
                          (faster iteration)
```

## Examples

### Watch Mode Timeout (Already Optimized)
- Watch mode fix already skipped builds (lines 1941-1962)
- Returns early with just: fix package.json → re-run test

### Syntax Error in Test File (Now Optimized)
- Fix syntax in test file → **skip build** → run test

### Syntax Error in Source File (Unchanged)
- Fix syntax in source file → **run build** → verify
- Build is still needed for production code validation

## Related Work

This optimization complements the watch mode auto-fix implementation (see `WATCH_MODE_AUTO_FIX_IMPLEMENTATION.md`), which also avoids unnecessary build steps when fixing watch mode timeouts.

## Files Modified

- **rev/execution/orchestrator.py** (lines 2174-2187)
  - Added test detection logic to skip builds for test fixes

## Files Created

- **tests/test_skip_build_for_test_fixes.py**
  - Comprehensive test coverage for the optimization
