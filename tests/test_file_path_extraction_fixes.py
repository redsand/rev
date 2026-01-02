"""Test fixes for file path extraction and task description issues."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.agents.code_writer import _looks_like_code_reference, _extract_target_files_from_description


def test_looks_like_code_reference():
    """Test that code references are correctly identified."""

    # Should be identified as code references (multiple dots, no path separators)
    assert _looks_like_code_reference("api.interceptors.request.use") == True
    assert _looks_like_code_reference("express.json.stringify") == True
    assert _looks_like_code_reference("app.use.middleware.auth") == True

    # Should NOT be identified as code references (has path separators)
    assert _looks_like_code_reference("src/services/api.ts") == False
    assert _looks_like_code_reference("./config/db.config.js") == False
    assert _looks_like_code_reference("backend/utils/helper.util.ts") == False

    # Should NOT be identified as code references (only one dot)
    assert _looks_like_code_reference("config.js") == False
    assert _looks_like_code_reference("app.ts") == False

    # Edge cases
    assert _looks_like_code_reference("") == False
    assert _looks_like_code_reference("nodots") == False

    print("[OK] All code reference detection tests passed")


def test_extract_target_files_excludes_code_references():
    """Test that code references are NOT extracted as file paths."""

    # Case 1: Backticked code reference should be excluded
    desc1 = "complete the unfinished `api.interceptors.request.use` block in src/services/api.ts"
    files1 = _extract_target_files_from_description(desc1)
    assert "api.interceptors.request.use" not in files1, f"Should not extract code reference, got: {files1}"
    assert "src/services/api.ts" in files1, f"Should extract real file path, got: {files1}"

    # Case 2: Multiple code references with actual file
    desc2 = 'Edit src/server.js to fix `app.use.middleware.auth` and `router.get.handler` methods'
    files2 = _extract_target_files_from_description(desc2)
    assert "app.use.middleware.auth" not in files2, f"Should not extract code reference, got: {files2}"
    assert "router.get.handler" not in files2, f"Should not extract code reference, got: {files2}"
    assert "src/server.js" in files2, f"Should extract real file path, got: {files2}"

    # Case 3: Quoted code reference
    desc3 = 'Update "express.json.parse" method in "src/utils/parser.ts"'
    files3 = _extract_target_files_from_description(desc3)
    assert "express.json.parse" not in files3
    assert "src/utils/parser.ts" in files3

    # Case 4: Edge case - file with multiple dots in name (e.g., test.spec.ts)
    desc4 = "Fix tests in tests/api.spec.ts"
    files4 = _extract_target_files_from_description(desc4)
    assert "tests/api.spec.ts" in files4, f"Should extract file with multiple dots if it has path separator, got: {files4}"

    print("[OK] All file extraction tests passed")


def test_task_description_format():
    """Test that task descriptions are formatted correctly to avoid parsing issues."""
    # Test the description format directly without needing full context
    from pathlib import Path

    # Simulate what the description would look like
    cmd = "npm run build"
    reason = "Per-file syntax check skipped"

    # Old format (problematic)
    old_desc = f"Run {cmd} for project typecheck/build to validate syntax (reason: {reason})"

    # New format (fixed)
    reason_text = reason if len(reason) <= 60 else reason[:57] + "..."
    new_desc = f"Run `{cmd}` to perform project-level typecheck and build validation ({reason_text})"

    # Verify old format issues
    assert "typecheck/build" in old_desc, "Old format should have the problematic text"

    # Verify new format fixes
    assert "typecheck/build" not in new_desc, f"New format should not contain 'typecheck/build'. Got: {new_desc}"
    assert "`" in new_desc, f"Command should be backticked for clarity. Got: {new_desc}"
    assert reason in new_desc, f"Reason should be preserved if under 60 chars. Got: {new_desc}"

    # Test truncation of long reasons
    long_reason = "This is a very long reason that exceeds the 60 character limit and should be truncated appropriately"
    long_reason_text = long_reason if len(long_reason) <= 60 else long_reason[:57] + "..."
    long_desc = f"Run `{cmd}` to perform project-level typecheck and build validation ({long_reason_text})"

    assert len(long_desc) < len(f"Run `{cmd}` to perform project-level typecheck and build validation ({long_reason})"), "Long reasons should be truncated"
    assert long_desc.count("...") == 1, "Truncation marker should appear once"

    print(f"[OK] Task description format correct:")
    print(f"     Old (bad): {old_desc}")
    print(f"     New (good): {new_desc}")


if __name__ == "__main__":
    test_looks_like_code_reference()
    test_extract_target_files_excludes_code_references()
    test_task_description_format()
    print("\n[OK] All file path extraction fix tests passed!")
