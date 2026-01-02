# Fix: Orchestrator Output Truncation Preventing Accurate Error Diagnosis

## Problem

The orchestrator was truncating command output (stderr/stdout) to only **300 characters** when building the work summary. This caused the LLM to repeatedly re-run commands like `npm run build` because it couldn't see the full error message needed to diagnose and fix the issue.

### Example Issue

When `npm run build` failed with a pinia resolution error:
```
error during build:
[vite]: Rollup failed to resolve import "pinia" from "C:/Users/champ/source/repos/test-app/src/main.ts".
This is most likely unintended because it can break your application at runtime.
```

The orchestrator would truncate this to:
```
{"rc": 1, "stdout": "...", "stderr": "...error during build:...
```

The LLM couldn't see "pinia" or the actual error, so it would create a new task to "rerun npm run build to capture the full error output" - leading to repeated identical tool calls.

## Root Cause

In `rev/execution/orchestrator.py` at line 5784-5785:
```python
if len(output_detail) > 300:
    output_detail = output_detail[:300] + '...'
```

This aggressive truncation was applied to all tool outputs, regardless of their importance for error diagnosis.

## Solution

Implemented **smart truncation** with these improvements:

### 1. **Increased Limits**
- Command tools (`run_cmd`, `run_tests`, `run_property_tests`): **2500 characters** (8x increase)
- Other tools: **800 characters** (2.6x increase)

### 2. **Intelligent Error Extraction**
For failed commands (rc != 0):
- Parse JSON output to separate stderr/stdout
- **Prioritize stderr** (contains actual error messages)
- When stderr > 2000 chars, intelligently extract error context:
  - Find error markers (`error:`, `Error:`, `Failed:`, etc.)
  - Extract 500 chars before + 1500 chars after the error
  - Preserve full stack traces and error messages

### 3. **Success Case Optimization**
For successful commands (rc == 0):
- Brief summary with first 800 chars of stdout
- No need for verbose output when commands succeed

### 4. **Fallback Handling**
- If output isn't JSON (plain text tools), apply generous 800-2500 char limits
- Gracefully handles malformed or non-standard tool outputs

## Code Changes

**File**: `rev/execution/orchestrator.py` (lines 5769-5837)

Key logic:
```python
# Smart truncation: parse command results to prioritize error information
if tool_name in ('run_cmd', 'run_tests', 'run_property_tests'):
    try:
        result_data = json.loads(summary)
        if isinstance(result_data, dict):
            rc = result_data.get('rc', 0)
            stderr = result_data.get('stderr', '').strip()
            stdout = result_data.get('stdout', '').strip()

            # For failed commands, prioritize stderr (contains error messages)
            if rc != 0 and stderr:
                # Extract the most relevant error portion
                # Keep up to 2000 chars of stderr for build/test errors
                if len(stderr) > 2000:
                    # Try to find error markers and keep content around them
                    error_markers = ['error:', 'Error:', 'ERROR:', 'failed', 'Failed', 'FAILED']
                    best_section = stderr[-2000:]  # Default to end

                    for marker in error_markers:
                        idx = stderr.rfind(marker)
                        if idx > 0:
                            # Get context around the error
                            start = max(0, idx - 500)
                            end = min(len(stderr), idx + 1500)
                            best_section = stderr[start:end]
                            if start > 0:
                                best_section = '...' + best_section
                            if end < len(stderr):
                                best_section = best_section + '...'
                            break

                    summary = json.dumps({
                        'rc': rc,
                        'stderr': best_section,
                        'stdout': stdout[:500] if stdout else ''
                    })
```

## Testing

Created `tests/test_orchestrator_output_truncation.py` with two test cases:

1. **test_command_error_output_not_truncated**: Verifies critical error information (like "pinia" import failure) is preserved
2. **test_successful_command_brief_summary**: Ensures successful commands get concise summaries

Both tests pass:
```
tests/test_orchestrator_output_truncation.py::test_command_error_output_not_truncated PASSED
tests/test_orchestrator_output_truncation.py::test_successful_command_brief_summary PASSED
```

## Impact

### Before Fix
- Commands with errors would be re-run 2-3+ times unnecessarily
- LLM couldn't diagnose build/test failures accurately
- Wasted tokens and time on duplicate tool calls

### After Fix
- **Single execution** provides complete error context
- LLM can immediately identify and fix issues (e.g., "pinia not installed")
- Faster debugging cycles with accurate information
- Reduced token usage by eliminating redundant commands

## Example Output Comparison

### Before (300 chars):
```
[COMPLETED] npm run build | Output: {"rc": 1, "stdout": "\n> test-app@0.1.0 build\n> vite build\n\nvite v5.4.21 building for production...\ntransforming...\n✓ 3 modules transformed.\n", "stderr": "x Build failed in 162ms\nerror during build:\n[vite]: Rollup failed to resolve import \"pin...
```
*(Error message cut off - LLM can't see "pinia" issue)*

### After (830-2500 chars):
```
[COMPLETED] npm run build | Output: {"rc": 1, "stderr": "x Build failed in 162ms\nerror during build:\n[vite]: Rollup failed to resolve import \"pinia\" from \"C:/Users/champ/source/repos/test-app/src/main.ts\".\nThis is most likely unintended because it can break your application at runtime.\nIf you do want to externalize this module explicitly add it to\n`build.rollupOptions.external`\n    at viteWarn (file:///C:/Users/champ/source/repos/test-app/node_modules/vite/dist/node/chunks/dep-BK3b2jBa.js:65855:17)\n    at onRollupWarning (file:///C:/Users/champ/source/repos/test-app/node_modules/vite/dist/node/chunks/dep-BK3b2jBa.js:65887:5)", "stdout": "\n> test-app@0.1.0 build\n> vite build\n\nvite v5.4.21 building for production...\ntransforming...\n✓ 3 modules transformed.\n"}
```
*(Full error preserved - LLM can immediately see "pinia" needs to be installed)*

## Files Changed

1. **rev/execution/orchestrator.py** - Implemented smart truncation logic
2. **tests/test_orchestrator_output_truncation.py** - Added comprehensive tests

## Related Issues

This fix addresses the pattern where rev would:
1. Run `npm run build` - sees truncated error
2. Run `npm run build` again "to capture full output" - sees same truncated error
3. Run `npm run build --verbose` - still truncated
4. Eventually timeout or give up

Now the first execution provides all needed information for accurate diagnosis and fixing.
