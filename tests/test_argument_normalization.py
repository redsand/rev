#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Simplified Argument Normalization.

Tests the simplified, configuration-driven argument normalization system.
"""

import unittest
from rev.tools.registry import _normalize_args, _PARAM_ALIASES, _TOOL_PARAM_ALIASES


class TestArgumentNormalization(unittest.TestCase):
    """Test argument normalization functionality."""

    def test_kebab_to_snake_conversion(self):
        """Kebab-case arguments are converted to snake_case."""
        args = {"file-path": "test.py", "old-string": "foo"}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["file_path"], "test.py")
        self.assertEqual(normalized["old_string"], "foo")

    def test_kebab_to_snake_preserves_snake(self):
        """Snake-case arguments are preserved."""
        args = {"file_path": "test.py", "path": "src"}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["file_path"], "test.py")
        self.assertEqual(normalized["path"], "src")

    def test_global_alias_file_path_to_path(self):
        """Global alias 'file_path' maps to 'path'."""
        args = {"file_path": "test.py"}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["path"], "test.py")

    def test_global_alias_filepath_to_path(self):
        """Global alias 'filepath' maps to 'path'."""
        args = {"filepath": "test.py"}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["path"], "test.py")

    def test_tool_specific_alias_read_file(self):
        """read_file tool specific aliases work."""
        test_cases = [
            ({"file": "test.py"}, "path"),
            ({"src": "test.py"}, "path"),
            ({"source": "test.py"}, "path"),
            ({"module": "test.py"}, "path"),
        ]

        for input_args, expected_key in test_cases:
            normalized = _normalize_args(input_args, "read_file")
            self.assertEqual(normalized[expected_key], "test.py")

    def test_tool_specific_alias_write_file(self):
        """write_file tool specific aliases work."""
        # Path aliases
        path_test_cases = [
            ({"file": "test.py"}, "path"),
            ({"dst": "test.py"}, "path"),
            ({"destination": "test.py"}, "path"),
            ({"target": "test.py"}, "path"),
        ]
        for input_args, expected_key in path_test_cases:
            normalized = _normalize_args(input_args, "write_file")
            self.assertEqual(normalized[expected_key], "test.py")

        # Content aliases
        content_test_cases = [
            ({"text": "content"}, "content"),
            ({"contents": "content"}, "content"),
        ]
        for input_args, expected_key in content_test_cases:
            normalized = _normalize_args(input_args, "write_file")
            self.assertEqual(normalized[expected_key], "content")

    def test_tool_specific_alias_replace_in_file(self):
        """replace_in_file tool specific aliases work."""
        args = {"file": "test.py", "old_string": "foo", "new_string": "bar"}
        normalized = _normalize_args(args, "replace_in_file")

        self.assertEqual(normalized["path"], "test.py")
        self.assertEqual(normalized["find"], "foo")
        self.assertEqual(normalized["replace"], "bar")

    def test_tool_specific_alias_run_cmd(self):
        """run_cmd tool specific aliases work."""
        test_cases = [
            ({"command": "ls"}, "cmd"),
            ({"cmdline": "ls"}, "cmd"),
            ({"shell_command": "ls"}, "cmd"),
            ({"run": "ls"}, "cmd"),
            ({"workdir": "/tmp"}, "cwd"),
            ({"working_dir": "/tmp"}, "cwd"),
        ]

        for input_args, expected_key in test_cases:
            normalized = _normalize_args(input_args, "run_cmd")
            self.assertEqual(normalized[expected_key], "ls" if expected_key == "cmd" else "/tmp")

    def test_tool_specific_alias_split_python_module(self):
        """split_python_module_classes aliases work."""
        args = {"module": "test_module.py", "output_dir": "output"}
        normalized = _normalize_args(args, "split_python_module_classes")

        self.assertEqual(normalized["source_path"], "test_module.py")
        self.assertEqual(normalized["target_directory"], "output")

    def test_priority_canonical_over_alias(self):
        """Canonical parameter name takes priority over alias."""
        args = {"path": "canonical.py", "file_path": "alias.py"}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["path"], "canonical.py")  # Keep canonical
        self.assertIn("file_path", normalized)  # Alias preserved

    def test_multiple_aliases_first_wins(self):
        """First matching alias is used when multiple are available."""
        args = {"file": "first.py", "src": "second.py"}
        normalized = _normalize_args(args, "read_file")

        # Should use "file" since it's checked first in the config
        self.assertEqual(normalized["path"], "first.py")

    def test_nested_arguments_unwrapped(self):
        """Nested {"arguments": {...}} wrapper is unwrapped."""
        args = {"arguments": {"path": "test.py"}}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["path"], "test.py")
        self.assertNotIn("arguments", normalized)

    def test_multiple_nested_unwraps(self):
        """Multiple levels of nested arguments are unwrapped."""
        args = {"arguments": {"arguments": {"path": "test.py"}}}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized["path"], "test.py")

    def test_no_normalization_for_non_dict(self):
        """Non-dict args are returned unchanged."""
        args = "not_a_dict"
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized, args)

    def test_empty_args(self):
        """Empty dict is handled."""
        args = {}
        normalized = _normalize_args(args, "read_file")

        self.assertEqual(normalized, {})

    def test_none_tool_name(self):
        """None tool name still applies global aliases."""
        args = {"file_path": "test.py"}
        normalized = _normalize_args(args, None)

        self.assertEqual(normalized["path"], "test.py")

    def test_case_insensitive_tool_name(self):
        """Tool name matching is case-insensitive."""
        args = {"file": "test.py"}
        normalized = _normalize_args(args, "READ_FILE")

        self.assertEqual(normalized["path"], "test.py")

    def test_unknown_tool_uses_global_aliases(self):
        """Unknown tool only uses global aliases."""
        args = {"file_path": "test.py", "command": "ls"}
        normalized = _normalize_args(args, "unknown_tool")

        self.assertEqual(normalized["path"], "test.py")
        # "command" is not a global alias, so it stays as-is
        self.assertIn("command", normalized)

    def test_original_values_preserved(self):
        """Original values are preserved during normalization."""
        args = {
            "file_path": "test.py",
            "content": "hello world",
            "count": 42,
            "flag": True,
            "list": ["a", "b", "c"],
            "dict": {"key": "value"},
        }
        normalized = _normalize_args(args, "write_file")

        self.assertEqual(normalized["path"], "test.py")
        self.assertEqual(normalized["content"], "hello world")
        self.assertEqual(normalized["count"], 42)
        self.assertEqual(normalized["flag"], True)
        self.assertEqual(normalized["list"], ["a", "b", "c"])
        self.assertEqual(normalized["dict"], {"key": "value"})


class TestAliasingConfiguration(unittest.TestCase):
    """Test the aliasing configuration data structures."""

    def test_param_aliases_structure(self):
        """_PARAM_ALIASES has correct structure."""
        self.assertIn("path", _PARAM_ALIASES)
        self.assertIn("file_path", _PARAM_ALIASES["path"])
        self.assertIn("content", _PARAM_ALIASES)

    def test_tool_param_aliases_structure(self):
        """_TOOL_PARAM_ALIASES has correct structure."""
        self.assertIn("read_file", _TOOL_PARAM_ALIASES)
        self.assertIn("write_file", _TOOL_PARAM_ALIASES)
        self.assertIn("run_cmd", _TOOL_PARAM_ALIASES)

    def test_tool_aliases_contain_lists(self):
        """Tool alias values are lists."""
        for tool, params in _TOOL_PARAM_ALIASES.items():
            for param, aliases in params.items():
                self.assertIsInstance(aliases, list)
                self.assertTrue(len(aliases) > 0)

    def test_global_aliases_contain_lists(self):
        """Global alias values are lists."""
        for param, aliases in _PARAM_ALIASES.items():
            self.assertIsInstance(aliases, list)


class TestBackwardsCompatibility(unittest.TestCase):
    """Test that normalization maintains backwards compatibility."""

    def test_common_patterns_from_original_code(self):
        """Test common patterns from the original implementation."""
        # Pattern 1: read_file with "file" alias
        args = {"file": "test.py"}
        normalized = _normalize_args(args, "read_file")
        self.assertEqual(normalized["path"], "test.py")

        # Pattern 2: write_file with "file" and "text" aliases
        args = {"file": "test.py", "text": "content"}
        normalized = _normalize_args(args, "write_file")
        self.assertEqual(normalized["path"], "test.py")
        self.assertEqual(normalized["content"], "content")

        # Pattern 3: replace_in_file with old_string/new_string
        args = {"file": "test.py", "old_string": "foo", "new_string": "bar"}
        normalized = _normalize_args(args, "replace_in_file")
        self.assertEqual(normalized["find"], "foo")
        self.assertEqual(normalized["replace"], "bar")

        # Pattern 4: run_cmd with "command" and "workdir"
        args = {"command": "ls", "workdir": "/tmp"}
        normalized = _normalize_args(args, "run_cmd")
        self.assertEqual(normalized["cmd"], "ls")
        self.assertEqual(normalized["cwd"], "/tmp")

        # Pattern 5: list_dir with "dir" alias
        args = {"dir": "src"}
        normalized = _normalize_args(args, "list_dir")
        self.assertEqual(normalized["pattern"], "src")

        # Pattern 6: create_directory with "directory" alias
        args = {"directory": "new_dir"}
        normalized = _normalize_args(args, "create_directory")
        self.assertEqual(normalized["path"], "new_dir")

    def test_mixed_case_aliases(self):
        """Mixed-case aliases work correctly."""
        args = {"FILE_PATH": "test.py"}
        normalized = _normalize_args(args, "read_file")

        # Global alias should work regardless of original casing
        self.assertIn("path", normalized)

    def test_list_type_aliases(self):
        """Aliases work for list-typed values (e.g., cmd)."""
        args = {"command": ["npm", "test"]}
        normalized = _normalize_args(args, "run_cmd")

        self.assertEqual(normalized["cmd"], ["npm", "test"])


class TestIntegrationScenarios(unittest.TestCase):
    """Test realistic integration scenarios."""

    def test_real_world_claude_call(self):
        """Simulate a realistic LLM tool call from Claude."""
        # Claude might emit this for reading a file
        args = {
            "file_path": "src/main.py",
        }
        normalized = _normalize_args(args, "read_file")
        self.assertEqual(normalized["path"], "src/main.py")

    def test_real_world_gpt_call(self):
        """Simulate a realistic LLM tool call from GPT."""
        # GPT might emit this for replacing content
        args = {
            "file": "src/main.py",
            "old_string": "old_code",
            "new_string": "new_code",
        }
        normalized = _normalize_args(args, "replace_in_file")
        self.assertEqual(normalized["path"], "src/main.py")
        self.assertEqual(normalized["find"], "old_code")
        self.assertEqual(normalized["replace"], "new_code")

    def test_complex_write_scenario(self):
        """Test a complex file writing scenario."""
        args = {
            "destination": "src/module.py",
            "text": "print('hello')",
        }
        normalized = _normalize_args(args, "write_file")
        self.assertEqual(normalized["path"], "src/module.py")
        self.assertEqual(normalized["content"], "print('hello')")

    def test_command_execution_with_directory(self):
        """Test command execution with working directory."""
        args = {
            "shell_command": ["python", "-m", "pytest"],
            "working_dir": "tests",
        }
        normalized = _normalize_args(args, "run_cmd")
        self.assertEqual(normalized["cmd"], ["python", "-m", "pytest"])
        self.assertEqual(normalized["cwd"], "tests")


if __name__ == "__main__":
    unittest.main()