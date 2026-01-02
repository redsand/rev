# test.environment File Path Extraction Fix

## Issue Found in Log `rev_run_20260101_232350.log`

### Massive Failure Cascade (60+ failed tasks)

**Lines 649, 897, 935, 1008, 1145, 1218, 1305** (and many more):
```
[90m → read_file[0m [90mReading file: C:\Users\champ\source\repos\test-app\test.environment[0m
[WARN] Cannot read target file: test.environment
[ERROR] Cannot read target file 'test.environment' for EDIT task
```

**Lines 132, 222, 353, 388, 463, 498, ...** (60+ failures):
```
✗ [FAILED] vitest.config.ts to change test.environment from 'jsdom' to 'node'
    | Reason: Write action completed without tool execution
```

**Problem**: The code writer extracted `test.environment` from task descriptions like:
- "change test.environment from 'jsdom' to 'node'"
- "update test.environment in vitest.config.ts"

It tried to read `test.environment` as a file when it's clearly a **config property reference** (like `test.environment` in JavaScript/TypeScript objects).

---

## Root Cause

Same category of bug as `app.listen` - property/method references treated as file paths.

### File: `rev/agents/code_writer.py`
### Function: `_looks_like_code_reference` (lines 24-127)

**Before Fix**:
```python
common_var_names = {
    'app', 'obj', 'this', 'self', 'that', 'req', 'res',
    'ctx', 'config', 'options', 'params', 'data', 'server',
    # ... missing 'test', 'environment', etc.
}

common_code_names = {
    'listen', 'main', 'module', 'exports', 'require', 'import',
    # ... missing 'environment', 'config', 'timeout', etc.
}
```

**Pattern Not Detected**:
- `test.environment` → parsed as filename "test" with extension "environment"
- "test" not in `common_var_names` ❌
- "environment" not in `common_code_names` ❌
- Result: Treated as file path ❌

---

## Fix Applied

### File: `rev/agents/code_writer.py:59-89`

**After Fix**:
```python
common_var_names = {
    'app', 'obj', 'this', 'self', 'that', 'req', 'res',
    'ctx', 'config', 'options', 'params', 'data', 'server',
    'client', 'router', 'express', 'fastify', 'koa',
    'console', 'process', 'window', 'document', 'global',
    'module', 'exports', 'require', 'import', 'JSON',
    'Math', 'Date', 'Array', 'Object', 'String', 'Number',
    'Promise', 'Error', 'Buffer',
    'test', 'tests', 'env', 'environment', 'settings',  # ✅ ADDED
    'props', 'state', 'store', 'theme', 'user', 'session'  # ✅ ADDED
}

common_code_names = {
    'listen', 'main', 'module', 'exports', 'require', 'import',
    'prototype', 'constructor', 'toString', 'valueOf',
    'length', 'push', 'pop', 'shift', 'map', 'filter',
    'reduce', 'forEach', 'find', 'includes',
    'log', 'error', 'warn', 'info', 'debug',
    'parse', 'stringify', 'join', 'split',
    'get', 'set', 'post', 'put', 'delete', 'patch',
    'use', 'apply', 'call', 'bind', 'then', 'catch',
    'next', 'send', 'status', 'text',
    'locals', 'session', 'cookies', 'query', 'params',
    'body', 'headers', 'path', 'url', 'method',
    'environment', 'timeout', 'retries', 'coverage', 'globals',  # ✅ ADDED
    'config', 'name', 'value', 'type', 'id', 'key'  # ✅ ADDED
}
```

**Pattern Now Detected**:
- `test.environment` → "test" in `common_var_names` ✅
- `config.timeout` → "config" in `common_var_names` AND `common_code_names` ✅
- `environment.name` → "environment" in both lists ✅
- Result: Correctly identified as code reference ✅

---

## Test Coverage

### Updated File: `tests/test_code_reference_detection.py`

**Added Test Cases** (lines 37-40):
```python
# Config property patterns (from real bug)
assert _looks_like_code_reference("test.environment") == True
assert _looks_like_code_reference("config.timeout") == True
assert _looks_like_code_reference("environment.name") == True
```

**All tests pass** ✅

---

## Real-World Impact

### Task Description Examples from Log:

1. **Line 463**: "update vitest.config.ts to set `test: { environment: 'node' }`"
   - **Before**: Extracted `test.environment` as file ❌
   - **After**: No false extraction ✅

2. **Line 630**: "change test.environment from 'jsdom' to 'node'"
   - **Before**: Tried to read file "test.environment" ❌
   - **After**: Recognized as property reference ✅

3. **Line 1091**: "in vitest.config.ts, change test.environment from 'jsdom' to 'node'"
   - **Before**: Error "Cannot read target file: test.environment" ❌
   - **After**: Only reads vitest.config.ts ✅

### Failure Cascade Prevented

**Before Fix**:
```
1. Task: "change test.environment in vitest.config.ts"
2. Extracted files: ['vitest.config.ts', 'test.environment']
3. Read vitest.config.ts ✓
4. Try to read test.environment ✗
5. Error: "Cannot read target file: test.environment"
6. LLM confused → returns text instead of tools
7. Circuit breaker: "LLM FAILED TO EXECUTE TOOLS"
8. Task fails, retry with similar description
9. Same error repeats 60+ times
```

**After Fix**:
```
1. Task: "change test.environment in vitest.config.ts"
2. Extracted files: ['vitest.config.ts']  # ✅ test.environment filtered out
3. Read vitest.config.ts ✓
4. Make edit successfully ✓
5. Task completes on first attempt
```

---

## Related Patterns Now Covered

### Common Config Property Patterns:
- `test.environment` (Vitest, Jest)
- `test.globals` (Vitest)
- `test.timeout` (test frameworks)
- `test.coverage` (test frameworks)
- `env.NODE_ENV` (environment variables)
- `config.retries` (test/app config)
- `settings.theme` (app config)
- `props.value` (React/Vue)
- `state.name` (state management)
- `user.id` (object properties)
- `session.timeout` (session config)

### Common Object Property Patterns:
- `app.listen` (Express)
- `express.json` (middleware)
- `console.log` (logging)
- `req.body`, `res.status` (HTTP)
- `process.env` (Node.js)
- `window.location` (browser)
- `Math.random` (built-ins)

All now correctly detected as code references, not file paths ✅

---

## Benefits

### Before Fix:
- ❌ 60+ task failures due to false file extraction
- ❌ Circuit breaker triggered repeatedly
- ❌ "LLM FAILED TO EXECUTE TOOLS" spam
- ❌ Wastes time, tokens, and user patience
- ❌ Config property references treated as files

### After Fix:
- ✅ Accurate property reference detection
- ✅ No false file read attempts
- ✅ Clean execution without errors
- ✅ Tasks complete on first attempt
- ✅ Handles all common config patterns

---

## Summary

**Fixed**: Extended code reference detection to recognize common config property patterns like `test.environment`, `config.timeout`, `environment.name`, etc.

**Impact**: Prevents massive failure cascades (60+ failures) when task descriptions mention config properties.

**Files Changed**:
- `rev/agents/code_writer.py:59-89` - Added test/environment/config patterns

**Tests Updated**:
- `tests/test_code_reference_detection.py:37-40` - Added config property tests

**Result**: Rev now correctly distinguishes between:
- **Config properties**: `test.environment`, `config.timeout` → code reference ✅
- **Config files**: `vitest.config.ts`, `jest.config.js` → file path ✅

This fix complements the `app.listen` fix and ensures rev handles all common JavaScript/TypeScript property patterns correctly.
