# Replace_In_File Preview Fix

## Problem

`replace_in_file` preview was showing:
```
--- Original Content
+++ New Content

(No changes)

Changes: 0 → 0 lines
```

User couldn't see the actual differences between old and new content.

---

## Root Cause

**Parameter naming mismatch** (third similar issue):

- **Tool definition** uses: `"find"` and `"replace"` parameters
- **CodeWriterAgent preview** was looking for: `"old_string"` and `"new_string"`

When the agent tried to get `arguments.get("old_string")` but the LLM passed `"find"`, it got empty string as default, resulting in no diff to display.

---

## Solution

**Location:** `rev/agents/code_writer.py` line 170-171

**Before (WRONG):**
```python
old_string = arguments.get("old_string", "")  # Wrong key!
new_string = arguments.get("new_string", "")  # Wrong key!
```

**After (CORRECT):**
```python
old_string = arguments.get("find", "")        # Correct key
new_string = arguments.get("replace", "")     # Correct key
```

---

## Expected Behavior After Fix

Now when replace_in_file is called, users see:

```
File: lib/utils.py

--- Original Content
+++ New Content

- def old_function():
-     return 42
+ def new_function():
+     return 100

Changes: 2 → 2 lines
```

Clear visibility into what's being replaced.

---

## Test Coverage

✅ **7 comprehensive tests - ALL PASSING**

1. `test_replace_in_file_displays_diff` - Verifies diff shows
2. `test_replace_in_file_shows_actual_content_diff` - Checks content visibility
3. `test_replace_in_file_with_multiline_change` - Tests multi-line replacements
4. `test_replace_in_file_parameter_consistency` - CRITICAL: Verifies parameter names match tool definition
5. `test_replace_in_file_empty_arguments_handled` - Edge case: empty replacements
6. `test_replace_in_file_one_liner_change` - Single-line replacements
7. `test_replace_in_file_header_footer_present` - Preview formatting

**Test Results:** 7/7 PASSING (0.60s)

---

## Files Changed

| File | Changes |
|------|---------|
| `rev/agents/code_writer.py` | 1 fix: parameter names on lines 170-171 |
| `tests/test_replace_in_file_preview.py` | NEW: 7 comprehensive tests |

---

## Why This Happened

This is the **third parameter naming mismatch** in the same file:

| Issue | Before | After | Status |
|-------|--------|-------|--------|
| 1. File path display | `"file_path"` | `"path"` | ✅ Fixed |
| 2. Replace preview | `"old_string"/"new_string"` | `"find"/"replace"` | ✅ Fixed |
| 3. ? | ? | ? | TBD |

The pattern: Tool definitions and code using the tools need to use **consistent parameter names**.

---

## Verification

Run tests anytime to verify the fix:
```bash
python -m pytest tests/test_replace_in_file_preview.py -v
```

Expected output:
```
7 passed in 0.60s
```

---

## Impact

### User Experience
- ✓ replace_in_file preview now shows actual diffs
- ✓ Users can see exactly what text will be replaced
- ✓ Full visibility before approval

### Code Quality
- ✓ Parameter names now consistent with tool definitions
- ✓ Comprehensive test coverage (7 tests)
- ✓ Prevents regression

---

**Status:** ✅ FIXED & TESTED
**Test Coverage:** 7/7 PASSING
**Ready for Production:** YES
