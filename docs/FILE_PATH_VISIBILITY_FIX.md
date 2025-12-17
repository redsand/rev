# File Path Visibility Fix

## Problem

File paths were showing as "unknown" in the CODE CHANGE PREVIEW output instead of displaying the actual file path.

### Example of the Bug
```
📝 CODE CHANGE PREVIEW
======================================================================

File: unknown
Action: CREATE
Size: 3 lines, 84 bytes

Preview (first 3 lines):
    1
    2  Analysts package __init__.py file.
    3  Exposes all analyst classes for easy importing.
```

User had no visibility into which file was being created/modified because the preview showed "File: unknown".

---

## Root Cause

**Parameter naming mismatch in `rev/agents/code_writer.py`**

The tool definitions (in `rev/tools/registry.py`) define the parameter as `"path"`:
```python
{
    "type": "function",
    "function": {
        "name": "write_file",
        "parameters": {
            "properties": {
                "path": {"type": "string", ...},  # KEY IS "path"
                "content": {"type": "string", ...}
            }
        }
    }
}
```

But the CodeWriterAgent was looking for `"file_path"` instead:
```python
# BUG: Looking for wrong key
file_path = arguments.get("file_path", "unknown")  # Returns "unknown" because key doesn't exist
```

When the key doesn't exist, Python's `.get()` method returns the default value `"unknown"`.

---

## Solution

Changed 4 locations in `rev/agents/code_writer.py` to use the correct key:

### Fix Locations

**File:** `rev/agents/code_writer.py`

| Line | Method | Change |
|------|--------|--------|
| 169 | `_display_change_preview()` | `arguments.get("file_path"` → `arguments.get("path"` |
| 187 | `_display_change_preview()` | `arguments.get("file_path"` → `arguments.get("path"` |
| 317 | `execute()` | `arguments.get("file_path"` → `arguments.get("path"` |
| 332 | `execute()` | `arguments.get('file_path'` → `arguments.get('path'` |

### Changes Made

**Before (WRONG):**
```python
def _display_change_preview(self, tool_name: str, arguments: dict) -> None:
    if tool_name == "replace_in_file":
        file_path = arguments.get("file_path", "unknown")  # ← WRONG KEY
    elif tool_name == "write_file":
        file_path = arguments.get("file_path", "unknown")  # ← WRONG KEY
```

**After (CORRECT):**
```python
def _display_change_preview(self, tool_name: str, arguments: dict) -> None:
    if tool_name == "replace_in_file":
        file_path = arguments.get("path", "unknown")  # ← CORRECT KEY
    elif tool_name == "write_file":
        file_path = arguments.get("path", "unknown")  # ← CORRECT KEY
```

---

## Expected Result After Fix

Now the CODE CHANGE PREVIEW shows the actual file path:

```
📝 CODE CHANGE PREVIEW
======================================================================

File: lib/analysts/__init__.py
Action: CREATE
Size: 3 lines, 84 bytes

Preview (first 3 lines):
    1
    2  Analysts package __init__.py file.
    3  Exposes all analyst classes for easy importing.
```

User has full visibility into which file is being created/modified.

---

## Test Coverage

Created comprehensive test suite: `tests/test_file_path_visibility.py`

### Test Results: 9/9 Passing

✓ `test_write_file_displays_correct_path` - Verifies write_file shows actual path
✓ `test_replace_in_file_displays_correct_path` - Verifies replace_in_file shows actual path
✓ `test_preview_header_and_footer_present` - Verifies preview formatting
✓ `test_write_file_with_multiline_content` - Tests with realistic file content
✓ `test_replace_in_file_shows_line_changes` - Tests diff preview
✓ `test_deeply_nested_file_paths` - Tests deeply nested paths like `src/features/auth/oauth2/google.py`
✓ `test_special_characters_in_file_paths` - Tests paths with hyphens, underscores, capitals
✓ `test_no_unknown_in_any_preview_output` - **CRITICAL**: Ensures "unknown" never appears
✓ `test_file_path_shown_during_approval_prompt` - Integration test for full execution flow

### Running Tests

```bash
# Run all file path visibility tests
python -m pytest tests/test_file_path_visibility.py -v

# Expected output:
# tests/test_file_path_visibility.py::TestFilePathVisibility::test_write_file_displays_correct_path PASSED
# tests/test_file_path_visibility.py::TestFilePathVisibility::test_replace_in_file_displays_correct_path PASSED
# ... (7 more tests)
# ======================== 9 passed in 0.54s =========================
```

---

## Impact

### User Experience
- ✓ File paths now clearly visible in CODE CHANGE PREVIEW
- ✓ Users can confirm which files will be modified before approval
- ✓ No more confusion from "unknown" file paths
- ✓ Better decision-making when approving/rejecting changes

### Code Quality
- ✓ Consistent parameter naming
- ✓ Reduces cognitive load (same key everywhere)
- ✓ Aligns with tool definitions
- ✓ Comprehensive test coverage prevents regression

---

## Files Changed

| File | Changes | Reason |
|------|---------|--------|
| `rev/agents/code_writer.py` | 4 locations updated | Fixed parameter key from "file_path" to "path" |
| `tests/test_file_path_visibility.py` | NEW file | Comprehensive test coverage (9 tests) |

---

## Verification

To verify the fix works:

1. Run the test suite:
   ```bash
   python -m pytest tests/test_file_path_visibility.py -v
   ```
   Expected: All 9 tests pass ✓

2. Run a real task with sub-agent mode:
   ```bash
   export REV_EXECUTION_MODE=sub-agent
   rev "Create a new file in lib/analysts/test.py with a test class"
   ```
   Expected: CODE CHANGE PREVIEW shows `File: lib/analysts/test.py` (not "unknown")

---

## Status

✅ **FIXED** - File paths now display correctly in CODE CHANGE PREVIEW
✅ **TESTED** - 9/9 tests passing
✅ **READY FOR PRODUCTION** - No breaking changes, improved user experience

---

**Last Updated:** 2025-12-16
**Status:** Complete
