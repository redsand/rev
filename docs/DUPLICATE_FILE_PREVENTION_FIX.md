# Duplicate File Prevention - Make Warnings Actionable

**Date**: 2025-12-25
**Issue**: Similar file warnings are reported but no action is taken
**Example**: `⚠️ Similar files exist: tests\api.test.js (61.5%), tests\user.test.js (69.2%), tests\user_crud.test.js (71.4%). Consider extending existing files instead of creating new one.`

---

## Problem

### Current Behavior
1. User creates new file with `write_file`
2. System detects similar files exist (e.g., `user_auth.test.js` when `user.test.js` already exists)
3. **Warning printed** to console: "⚠️ Similar files exist..."
4. **File is created anyway** - warning is ignored
5. Result: Duplicate/fragmented test files

### Why This Happens

**File**: `rev/tools/file_ops.py:195`

```python
if similar_files:
    files_str = ", ".join(f"{s['path']} ({s['similarity']})" for s in similar_files[:3])
    warnings.append(
        f"Similar files exist: {files_str}. "
        f"Consider extending existing files instead of creating new one."
    )
```

**File**: `rev/tools/file_ops.py:286-289`

```python
if check_result.get('warnings'):
    # Log warnings (visible to user/LLM)
    for warning in check_result['warnings']:
        print(f"  ⚠️  {warning}")  # <-- Just prints, doesn't prevent
```

**Result**: Warning is printed, file is created, execution continues. No action taken.

---

## The Fix

### Make Verification Fail on Duplicates

**File**: `rev/execution/quick_verify.py:871-898`

Added check in `_verify_file_creation()` after confirming file exists:

```python
# CRITICAL CHECK: Detect similar/duplicate files and fail verification
# This forces replanning to extend existing files instead of creating duplicates
payload = _parse_task_result_payload(task.result)
if payload and payload.get("is_new_file") and payload.get("similar_files"):
    similar_list = payload.get("similar_files", [])
    similar_str = ", ".join(similar_list[:3])

    # Add agent request with guidance for planner
    context.add_agent_request(
        "DUPLICATE_FILE_PREVENTION",
        {
            "agent": "VerificationSystem",
            "reason": f"Similar files exist: {similar_str}",
            "detailed_reason": (
                f"DUPLICATE FILE DETECTED: File '{file_path.name}' was created but similar files already exist: {similar_str}. "
                f"Instead of creating new files with similar names, EDIT one of the existing files to add the new functionality. "
                f"Use action_type='edit' with the most appropriate existing file path."
            )
        }
    )

    # Fail verification to trigger replan
    return VerificationResult(
        passed=False,
        message=f"Duplicate file: similar files exist ({similar_str}). Extend existing file instead of creating new one.",
        details={
            **details,
            "similar_files": similar_list,
            "suggested_action": "extend_existing"
        },
        should_replan=True  # Triggers adaptive replan
    )
```

---

## How It Works

### Before Fix

```
1. Planner: [ADD] create tests/user_auth.test.js
2. CodeWriter: Executes write_file('tests/user_auth.test.js')
3. File ops: Detects user.test.js (69% similar)
4. File ops: Prints "⚠️ Similar files exist: tests/user.test.js (69.2%)"
5. File ops: Creates file anyway
6. Verification: File exists, size > 0 → PASS ✓
7. Continue with duplicate file created
```

### After Fix

```
1. Planner: [ADD] create tests/user_auth.test.js
2. CodeWriter: Executes write_file('tests/user_auth.test.js')
3. File ops: Detects user.test.js (69% similar)
4. File ops: Prints "⚠️ Similar files exist: tests/user.test.js (69.2%)"
5. File ops: Creates file, includes similar_files in result
6. Verification: Detects is_new_file + similar_files → FAIL ✗
7. Agent request added: "DUPLICATE FILE DETECTED: use action_type='edit' instead"
8. Adaptive replan triggered
9. Planner: [EDIT] tests/user.test.js to add auth functionality
```

---

## Expected Behavior

### Scenario 1: Creating Similar File

**Task**: `[ADD] create tests/user_auth.test.js`

**Existing files**: `tests/user.test.js` (69% similar)

**Before**:
- Warning printed
- File created
- Tests split across multiple files

**After**:
- Verification fails
- Agent request: "Similar files exist: tests/user.test.js"
- Replan with guidance: "EDIT tests/user.test.js instead"
- Planner creates EDIT task to extend existing file

### Scenario 2: Creating Unique File

**Task**: `[ADD] create tests/database.test.js`

**Existing files**: `tests/user.test.js`, `tests/api.test.js` (0-30% similar - below threshold)

**Before**: File created ✓

**After**: File created ✓ (no change - similarity below 60% threshold)

---

## Configuration

**File**: `rev/tools/file_ops.py`

```python
SIMILARITY_THRESHOLD = 0.60  # 60% similarity triggers warning
WARN_ON_NEW_FILES = True      # Enable duplicate detection
```

**Threshold Explanation**:
- **60-100%**: Similar enough to be duplicates (triggers failure)
- **30-59%**: Somewhat related but different enough
- **0-29%**: Unrelated files

**Example Similarities**:
- `user.test.js` vs `user_auth.test.js` → 69% (duplicate)
- `user.test.js` vs `api.test.js` → 25% (different)
- `login.vue` vs `login_form.vue` → 71% (duplicate)

---

## Impact

### Code Quality
- **Before**: Test files fragmented (user.test.js, user_auth.test.js, user_crud.test.js)
- **After**: Consolidated test files (all user functionality in user.test.js)

### Maintenance
- **Before**: Changes require updating multiple similar files
- **After**: Single file to maintain per feature

### DRY Principle
- **Before**: Duplicate setup/teardown code across similar files
- **After**: Shared setup in single file, cleaner structure

---

## Edge Cases

### Case 1: Legitimately Similar Names

**Example**: `frontend/Login.vue` and `backend/login.js`

**Solution**: Different directories, likely different purposes. Similarity detection is per-directory only.

### Case 2: High Similarity but Different Purpose

**Example**: `user_test_helpers.js` vs `user.test.js` (70% similar)

**Solution**: If verification fails incorrectly, user can approve override or the planner will learn from feedback.

### Case 3: Multiple Similar Files

**Example**: Create `user_profile.test.js` when `user.test.js`, `user_crud.test.js` exist

**Solution**: Verification shows all similar files (up to 3), lets planner choose most appropriate to extend.

---

## Rollback Plan

If this causes issues, disable with:

```python
# rev/tools/file_ops.py
WARN_ON_NEW_FILES = False  # Disable duplicate detection
```

Or adjust threshold:

```python
SIMILARITY_THRESHOLD = 0.80  # Only trigger on 80%+ similarity (stricter)
```

---

## Testing

### Test Case 1: Duplicate Detection Works

```python
# Create user.test.js
write_file("tests/user.test.js", "test content")

# Try to create user_auth.test.js (similar name)
result = write_file("tests/user_auth.test.js", "auth test")
verification = verify_task_execution(task, context)

# Expected: Verification fails with similar files message
assert verification.passed == False
assert "similar files exist" in verification.message.lower()
assert "user.test.js" in str(verification.details.get("similar_files"))
```

### Test Case 2: Unique File Creation Works

```python
# Create user.test.js
write_file("tests/user.test.js", "test content")

# Create database.test.js (completely different)
result = write_file("tests/database.test.js", "db test")
verification = verify_task_execution(task, context)

# Expected: Verification passes (files not similar)
assert verification.passed == True
```

---

## Files Modified

1. **`rev/execution/quick_verify.py`** (lines 871-898)
   - Added similar file detection in `_verify_file_creation()`
   - Fails verification when duplicates detected
   - Adds agent request with guidance

---

## Summary

**Problem**: Warnings about similar files were printed but ignored, leading to duplicate files.

**Solution**: Make verification fail when similar files exist, triggering adaptive replan with guidance to extend existing files instead.

**Philosophy**: "Simpler is better" - Consolidate related functionality in existing files rather than creating fragmented duplicates.

**Result**: Cleaner codebase, fewer duplicate files, better maintainability.
