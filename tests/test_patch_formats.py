#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for patch format handling and ANSI stripping."""

import json
import tempfile
import os
from pathlib import Path

from rev.tools.git_ops import _normalize_patch_text, apply_patch


class TestANSIStripping:
    """Test ANSI escape code stripping from patches."""

    def test_ansi_codes_stripped_from_patch(self):
        """ANSI color codes should be removed from patch content."""
        patch_with_ansi = """\x1b[32m+new line\x1b[0m
\x1b[31m-old line\x1b[0m
\x1b[36m@@ -1,1 +1,1 @@\x1b[0m"""

        normalized = _normalize_patch_text(patch_with_ansi)

        assert "\x1b" not in normalized
        assert "+new line" in normalized
        assert "-old line" in normalized
        assert "@@ -1,1 +1,1 @@" in normalized

    def test_ansi_green_red_cyan_stripped(self):
        """Common color codes (green, red, cyan) should be stripped."""
        # Green for additions
        assert "\x1b[32m" not in _normalize_patch_text("\x1b[32m+added\x1b[0m")
        # Red for deletions
        assert "\x1b[31m" not in _normalize_patch_text("\x1b[31m-removed\x1b[0m")
        # Cyan for headers
        assert "\x1b[36m" not in _normalize_patch_text("\x1b[36m@@\x1b[0m")

    def test_content_preserved_after_stripping(self):
        """Actual content should be preserved after ANSI stripping."""
        patch = "\x1b[32m+import express from 'express';\x1b[0m"
        normalized = _normalize_patch_text(patch)
        assert "+import express from 'express';" in normalized


class TestUnifiedDiffFormat:
    """Test unified diff format handling."""

    def test_valid_unified_diff_structure(self):
        """Valid unified diff should have proper structure after normalization."""
        patch = """--- a/test.txt
+++ b/test.txt
@@ -1 +1 @@
-old content
+new content
"""
        normalized = _normalize_patch_text(patch)
        # Check structure is preserved
        assert "--- a/test.txt" in normalized
        assert "+++ b/test.txt" in normalized
        assert "@@ -1 +1 @@" in normalized
        assert "-old content" in normalized
        assert "+new content" in normalized


class TestCodexPatchFormat:
    """Test Codex patch format handling."""

    def test_codex_patch_detected(self):
        """Codex patch format should be recognized."""
        patch = """*** Begin Patch
*** Update File: test.txt
@@ context line
-old line
+new line
*** End Patch
"""
        normalized = _normalize_patch_text(patch)
        assert "*** Begin Patch" in normalized

    def test_codex_add_file_format(self):
        """Codex Add File format should be valid."""
        patch = """*** Begin Patch
*** Add File: new_file.txt
+line 1
+line 2
*** End Patch
"""
        normalized = _normalize_patch_text(patch)
        assert "*** Add File:" in normalized


class TestPlaceholderTestScript:
    """Test placeholder test script detection."""

    def test_placeholder_detected(self):
        """Placeholder npm test script should be detected."""
        from rev.tools.project_types import _is_placeholder_test_script

        assert _is_placeholder_test_script('echo "Error: no test specified" && exit 1')
        assert _is_placeholder_test_script('echo "no test specified" && exit 1')

    def test_real_script_not_placeholder(self):
        """Real test scripts should not be marked as placeholder."""
        from rev.tools.project_types import _is_placeholder_test_script

        assert not _is_placeholder_test_script("vitest run")
        assert not _is_placeholder_test_script("jest")
        assert not _is_placeholder_test_script("pytest")
        assert not _is_placeholder_test_script("npm run test:unit")


class TestCheckpointAgentState:
    """Test agent state persistence in checkpoints."""

    def test_agent_state_saved_in_checkpoint(self, tmp_path):
        """Agent state should be included in checkpoint files."""
        from rev.models.task import ExecutionPlan, Task

        plan = ExecutionPlan([Task(description="test task")])
        agent_state = {
            "total_recovery_attempts": 5,
            "recovery_attempts": {"task_1": 2},
            "transient_data": "should_not_persist",
        }

        checkpoint_path = tmp_path / "test_checkpoint.json"
        plan.save_checkpoint(str(checkpoint_path), agent_state=agent_state)

        # Load and verify
        loaded_plan, loaded_state = ExecutionPlan.load_checkpoint(str(checkpoint_path))

        assert loaded_state.get("total_recovery_attempts") == 5
        assert loaded_state.get("recovery_attempts") == {"task_1": 2}
        # transient_data should not be persisted (not in persistent_keys)
        assert "transient_data" not in loaded_state

    def test_checkpoint_without_agent_state(self, tmp_path):
        """Checkpoint without agent_state should load with empty dict."""
        from rev.models.task import ExecutionPlan, Task

        plan = ExecutionPlan([Task(description="test task")])
        checkpoint_path = tmp_path / "test_checkpoint.json"
        plan.save_checkpoint(str(checkpoint_path))

        loaded_plan, loaded_state = ExecutionPlan.load_checkpoint(str(checkpoint_path))
        assert loaded_state == {}


class TestSyntaxCheck:
    """Test syntax checking for 'already correct' claims.

    Note: These tests use Python's ast module directly since the full
    _quick_syntax_check function depends on workspace path resolution.
    """

    def test_python_ast_parse_valid(self):
        """Valid Python code should parse with ast."""
        import ast
        code = "def hello():\n    return 'world'\n"
        # Should not raise
        ast.parse(code)

    def test_python_ast_parse_invalid(self):
        """Invalid Python code should raise SyntaxError."""
        import ast
        code = "def broken("  # Missing closing paren
        try:
            ast.parse(code)
            assert False, "Should have raised SyntaxError"
        except SyntaxError:
            pass  # Expected

    def test_json_loads_valid(self):
        """Valid JSON should parse successfully."""
        content = '{"key": "value"}'
        parsed = json.loads(content)
        assert parsed["key"] == "value"

    def test_json_loads_invalid(self):
        """Invalid JSON should raise JSONDecodeError."""
        content = '{"key": value}'  # Missing quotes
        try:
            json.loads(content)
            assert False, "Should have raised JSONDecodeError"
        except json.JSONDecodeError:
            pass  # Expected

    def test_external_check_helper_skips_missing_command(self):
        """_run_external_check should skip when command not found."""
        from rev.agents.code_writer import _run_external_check

        passed, msg = _run_external_check(["nonexistent_command_xyz123", "--version"])
        assert passed is True  # Should not block
        assert "not found" in msg.lower() or "skipped" in msg.lower()
