# Code Reference Detection Fix - Complete Solution

## Issue Found in Log `rev_run_20260101_224547.log`

### Error on Lines 1019-1024:
```
CodeWriterAgent executing task: refactor src/server.ts to export the Express `app` instance (removing or guarding the unconditional `app.listen` call behind `if (require.main === module)`) so tests can import and run against the app without hanging.
  → read_file Reading file: app.listen
  → read_file Reading file: C:\Users\champ\source\repos\test-app\app.listen
  [WARN] Cannot read target file: app.listen
  → read_file Reading file: src/server.ts
```

**Problem**: The code writer extracted `app.listen` from the backticked phrase in the task description and tried to read it as a file, when it's clearly a method call (code reference).

**Root Cause**: The file path extraction logic in `rev/agents/code_writer.py` only detected multi-dot patterns (2+ dots) as code references. Single-dot patterns like `app.listen`, `console.log`, `express.json` were incorrectly treated as file paths.

---

## User's Question

> "do we have to get the filename from text or is there a json object in a tools response that has the correct value?"

**Answer**: After investigating the planner LLM output format (`rev/execution/planner.py`), the task structure only contains:
```json
{
  "description": string,
  "action_type": string,
  "complexity": string
}
```

**There is NO structured `target_files` field.** File paths are embedded in the free-text `description`, so we MUST parse them from the description text. This makes accurate detection critical.

---

## Fix Applied

### File: `rev/agents/code_writer.py`

**Enhanced Function**: `_looks_like_code_reference(text: str, context: str = "") -> bool`

**New Detection Strategy** (in priority order):

1. **Path Separators Check** (lines 37-40)
   - If text contains `/` or `\`, it's a file path
   - Example: `src/server.ts` → **file path**

2. **Multi-Dot Patterns** (lines 43-48)
   - 2+ dots without path separators = code reference
   - Example: `api.interceptors.request.use` → **code**

3. **Common Variable/Object Names** (lines 57-69)
   - Checks if prefix is a known variable name
   - Examples: `app.listen`, `console.log`, `express.json`, `Math.random` → **code**
   - Includes: app, obj, req, res, console, process, JSON, Math, etc.

4. **Common Method/Property Names** (lines 71-87)
   - Checks if suffix is a known method/property
   - Examples: `server.listen`, `obj.stringify`, `router.use` → **code**
   - Includes: listen, main, module, log, parse, get, set, etc.

5. **Context Keywords** (lines 89-99)
   - Analyzes surrounding text for code-related words
   - Keywords: call, method, guard, wrap, middleware, etc.
   - Example: "wrap the `app.listen` call" → context indicates **code**

6. **Config File Patterns** (lines 112-120)
   - Special handling for known config files
   - Examples: `package.json`, `tsconfig.json` → **file**

7. **File Extensions** (lines 101-124)
   - Last resort: check for common file extensions
   - Extensions: js, ts, py, json, md, etc.
   - Only applies if previous checks didn't identify as code

### Updated Extraction Logic (lines 116-183)

All three extraction patterns (backticks, quotes, bare) now:
1. Extract 50 characters of context before and after the match
2. Pass both candidate and context to `_looks_like_code_reference()`
3. Filter out detected code references

**Before**:
```python
if _looks_like_code_reference(candidate):  # Only checked 2+ dots
    continue
```

**After**:
```python
context_start = max(0, match.start() - 50)
context_end = min(len(description), match.end() + 50)
context = description[context_start:context_end]
if _looks_like_code_reference(candidate, context):  # Smart detection with context
    continue
```

---

## Test Coverage

**New File**: `tests/test_code_reference_detection.py`

### Test Cases:

1. **`test_app_listen_is_code_reference()`**
   - ✅ Verifies `app.listen` is detected as code
   - ✅ Tests with context: "wrap the `app.listen` call"

2. **`test_real_files_not_filtered()`**
   - ✅ `src/server.ts` → file
   - ✅ `package.json` → file
   - ✅ `tests/api.test.ts` → file

3. **`test_common_code_patterns()`**
   - ✅ `console.log` → code
   - ✅ `JSON.parse` → code
   - ✅ `express.json` → code
   - ✅ `req.body` → code
   - ✅ `require.main` → code

4. **`test_multi_dot_patterns()`**
   - ✅ `api.interceptors.request.use` → code
   - ✅ `express.json.stringify` → code

5. **`test_extract_from_description_app_listen()`**
   - Task: "refactor src/server.ts to export `app` and wrap `app.listen` call"
   - ✅ Extracts: `src/server.ts`
   - ✅ Filters out: `app.listen`, `require.main`

6. **`test_extract_from_description_backticks()`**
   - Task: "modify `src/server.ts` to add `app.listen(PORT)` call"
   - ✅ Extracts: `src/server.ts`
   - ✅ Filters out: `app.listen`

7. **`test_extract_from_description_mixed()`**
   - Task with files and code: `src/routes.ts`, `tests/api.test.ts`, `router.get`, `req.params`, `express.json()`
   - ✅ Extracts files only
   - ✅ Filters all code references

8. **`test_context_clues()`**
   - ✅ "guard the app.listen call" → detected via context
   - ✅ "wrap the server.start call" → detected via context

9. **`test_edge_cases()`**
   - ✅ Empty strings handled
   - ✅ No-dot patterns ignored
   - ✅ `src/listen.ts` correctly identified as file despite "listen" being a method name

**All tests pass** ✅

---

## Real-World Examples

### Example 1: The Original Error
**Task Description**:
```
refactor src/server.ts to export the Express `app` instance (removing or guarding
the unconditional `app.listen` call behind `if (require.main === module)`)
```

**Before Fix**:
- Extracted: `['src/server.ts', 'app.listen', 'require.main']`
- Tried to read: `app.listen` as a file ❌
- Result: [WARN] Cannot read target file: app.listen

**After Fix**:
- Extracted: `['src/server.ts']` ✅
- Only reads actual file
- Code references filtered out

### Example 2: Express Middleware
**Task Description**:
```
add middleware `express.json()` and `cors()` to `src/app.ts`
```

**Before Fix**:
- Extracted: `['express.json', 'cors', 'src/app.ts']`
- Tried to read: `express.json` and `cors` ❌

**After Fix**:
- Extracted: `['src/app.ts']` ✅
- Filters: `express.json` (variable name "express" detected)
- Filters: `cors()` (has `(` immediately after)

### Example 3: Config Files vs Code
**Task Description**:
```
update `package.json` and configure `express.json` middleware
```

**Before Fix**:
- Would extract both ❌
- Confused `package.json` with `express.json`

**After Fix**:
- Extracted: `['package.json']` ✅
- `package.json` → file (config file pattern)
- `express.json` → code (variable name + middleware context)

---

## Benefits

### Before Fix:
- ❌ `app.listen`, `console.log`, `express.json` treated as files
- ❌ Wasted tool calls trying to read non-existent files
- ❌ Warning spam in logs
- ❌ LLM confused by missing file errors
- ❌ Increased latency and token usage

### After Fix:
- ✅ Accurate detection of code vs file paths
- ✅ No wasted tool calls on code references
- ✅ Clean logs without false warnings
- ✅ LLM gets correct file list
- ✅ Reduced latency and cost
- ✅ Handles all common patterns: `obj.method`, `require.main`, `app.listen`, etc.

---

## Summary

The fix implements a **4-tier detection system**:

1. **Structural analysis**: Check for path separators and dot count
2. **Lexical analysis**: Match against known variable/method names
3. **Contextual analysis**: Examine surrounding text for code keywords
4. **Extension analysis**: File extension check as fallback

This ensures accurate differentiation between:
- **Code references**: `app.listen`, `console.log`, `express.json()`, `require.main`
- **File paths**: `src/server.ts`, `package.json`, `tests/api.test.ts`

The solution is **context-aware**, **comprehensive**, and **tested** with real-world examples from the log.
