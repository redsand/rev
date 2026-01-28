#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Tool Error Taxonomy.

Tests the unified error classification system for tool execution.
"""

import unittest
from rev.tools.errors import (
    ToolErrorType,
    ToolError,
    file_not_found_error,
    permission_denied_error,
    syntax_error,
    timeout_error,
    validation_error,
)


class TestToolErrorType(unittest.TestCase):
    """Test ToolErrorType enum properties."""

    def test_retryable_errors(self):
        """Correct errors are marked as retryable."""
        retryable = {
            ToolErrorType.TRANSIENT,
            ToolErrorType.TIMEOUT,
            ToolErrorType.NETWORK,
        }
        for error_type in ToolErrorType:
            self.assertEqual(
                error_type.is_retryable,
                error_type in retryable,
                f"{error_type} retryable property mismatch"
            )

    def test_recoverable_by_agent_errors(self):
        """Correct errors are recoverable by agent without user help."""
        recoverable = {
            ToolErrorType.TRANSIENT,
            ToolErrorType.TIMEOUT,
            ToolErrorType.NETWORK,
            ToolErrorType.NOT_FOUND,
            ToolErrorType.SYNTAX_ERROR,
            ToolErrorType.VALIDATION_ERROR,
        }
        for error_type in ToolErrorType:
            self.assertEqual(
                error_type.recoverable_by_agent,
                error_type in recoverable,
                f"{error_type} recoverable_by_agent property mismatch"
            )

    def test_requires_user_input_errors(self):
        """Correct errors require user input."""
        requires_input = {
            ToolErrorType.PERMISSION_DENIED,
            ToolErrorType.CONFLICT,
        }
        for error_type in ToolErrorType:
            self.assertEqual(
                error_type.requires_user_input,
                error_type in requires_input,
                f"{error_type} requires_user_input property mismatch"
            )


class TestToolError(unittest.TestCase):
    """Test ToolError dataclass."""

    def test_create_basic_error(self):
        """Can create a basic ToolError."""
        error = ToolError(
            error_type=ToolErrorType.NOT_FOUND,
            message="File not found",
        )
        self.assertEqual(error.error_type, ToolErrorType.NOT_FOUND)
        self.assertEqual(error.message, "File not found")
        self.assertTrue(error.recoverable)

    def test_to_dict_conversion(self):
        """ToolError can be converted to dict."""
        error = ToolError(
            error_type=ToolErrorType.SYNTAX_ERROR,
            message="Syntax error in generated code",
            context={"line": 42},
            recoverable=True,
            suggested_recovery=["Check brackets"],
            original_error="SyntaxError: unexpected EOF",
        )
        error_dict = error.to_dict()

        self.assertEqual(error_dict["error_type"], "syntax_error")
        self.assertEqual(error_dict["error"], "Syntax error in generated code")
        self.assertEqual(error_dict["context"]["line"], 42)
        self.assertTrue(error_dict["recoverable"])
        self.assertIn("Check brackets", error_dict["suggested_recovery"])
        self.assertEqual(error_dict["original_error"], "SyntaxError: unexpected EOF")

    def test_from_dict_conversion(self):
        """ToolError can be created from dict."""
        data = {
            "error_type": "not_found",
            "error": "File missing",
            "context": {"file": "test.py"},
            "recoverable": True,
            "suggested_recovery": ["Search for file"],
            "original_error": "FileNotFoundError: [Errno 2]",
        }
        error = ToolError.from_dict(data)

        self.assertEqual(error.error_type, ToolErrorType.NOT_FOUND)
        self.assertEqual(error.message, "File missing")
        self.assertEqual(error.context["file"], "test.py")
        self.assertTrue(error.recoverable)
        self.assertIn("Search for file", error.suggested_recovery)

    def test_from_dict_unknown_error_type(self):
        """Unknown error type falls back to UNKNOWN."""
        data = {
            "error_type": "invalid_type",
            "error": "Some error",
        }
        error = ToolError.from_dict(data)

        self.assertEqual(error.error_type, ToolErrorType.UNKNOWN)

    def test_from_dict_backward_compatibility(self):
        """Can parse old-style error responses."""
        # Old format: just "error" field
        data = {"error": "Something went wrong"}
        error = ToolError.from_dict(data)
        self.assertEqual(error.error_type, ToolErrorType.UNKNOWN)
        self.assertEqual(error.message, "Something went wrong")

    def test_from_exception_file_not_found(self):
        """FileNotFoundError is classified as NOT_FOUND."""
        exc = FileNotFoundError("test.py")
        error = ToolError.from_exception(exc, "read_file")

        self.assertEqual(error.error_type, ToolErrorType.NOT_FOUND)
        self.assertIn("read_file", error.message)
        self.assertIn("test.py", error.message)
        self.assertTrue(error.recoverable)

    def test_from_exception_permission_denied(self):
        """PermissionError is classified as PERMISSION_DENIED."""
        exc = PermissionError("Permission denied: /root/file")
        error = ToolError.from_exception(exc, "write_file")

        self.assertEqual(error.error_type, ToolErrorType.PERMISSION_DENIED)
        self.assertFalse(error.recoverable)

    def test_from_exception_timeout(self):
        """TimeoutError is classified as TIMEOUT."""
        exc = TimeoutError("Operation timed out")
        error = ToolError.from_exception(exc, "run_cmd")

        self.assertEqual(error.error_type, ToolErrorType.TIMEOUT)
        self.assertTrue(error.recoverable)

    def test_from_exception_syntax_error(self):
        """SyntaxError is classified as SYNTAX_ERROR."""
        exc = SyntaxError("unexpected EOF while parsing")
        error = ToolError.from_exception(exc, "code_generation")

        self.assertEqual(error.error_type, ToolErrorType.SYNTAX_ERROR)
        self.assertTrue(error.recoverable)

    def test_from_exception_value_error(self):
        """ValueError is classified as VALIDATION_ERROR."""
        exc = ValueError("Invalid argument: -1")
        error = ToolError.from_exception(exc, "tool")

        self.assertEqual(error.error_type, ToolErrorType.VALIDATION_ERROR)
        self.assertTrue(error.recoverable)

    def test_from_exception_with_custom_type(self):
        """Can override auto-classification with custom type."""
        exc = FileNotFoundError("missing.py")
        error = ToolError.from_exception(
            exc,
            "custom_tool",
            custom_type=ToolErrorType.UNKNOWN,
        )

        self.assertEqual(error.error_type, ToolErrorType.UNKNOWN)

    def test_suggested_recovery_for_not_found(self):
        """NOT_FOUND errors have appropriate recovery suggestions."""
        error = file_not_found_error("src/main.py")
        suggestions = error.suggested_recovery

        self.assertIn("search_code", suggestions[0].lower())
        self.assertTrue(len(suggestions) > 0)

    def test_suggested_recovery_for_permission_denied(self):
        """PERMISSION_DENIED errors have appropriate recovery suggestions."""
        error = permission_denied_error("/root/secret.txt")
        suggestions = error.suggested_recovery

        self.assertIn("permission", suggestions[0].lower())
        self.assertFalse(error.recoverable)

    def test_suggested_recovery_for_syntax_error(self):
        """SYNTAX_ERROR errors have appropriate recovery suggestions."""
        error = syntax_error("unexpected EOF", "test.py")
        suggestions = error.suggested_recovery

        self.assertIn("syntax", suggestions[0].lower())
        self.assertTrue(error.recoverable)

    def test_suggested_recovery_for_timeout(self):
        """TIMEOUT errors have appropriate recovery suggestions."""
        error = timeout_error("npm install", 30)
        suggestions = error.suggested_recovery

        self.assertIn("timeout", error.message.lower())
        self.assertTrue(len(suggestions) > 0)

    def test_suggested_recovery_for_validation_error(self):
        """VALIDATION_ERROR errors have appropriate recovery suggestions."""
        error = validation_error("Missing required field 'name'", {"name": None})
        suggestions = error.suggested_recovery

        self.assertIn("validation", error.message.lower())
        self.assertTrue(error.recoverable)


class TestErrorFactoryFunctions(unittest.TestCase):
    """Test convenience factory functions."""

    def test_file_not_found_error_factory(self):
        """file_not_found_error creates proper error."""
        error = file_not_found_error("missing.py", "read_file")

        self.assertEqual(error.error_type, ToolErrorType.NOT_FOUND)
        self.assertIn("missing.py", error.message)
        self.assertIn("read_file", error.message)
        self.assertEqual(error.context["file_path"], "missing.py")
        self.assertTrue(error.recoverable)

    def test_permission_denied_error_factory(self):
        """permission_denied_error creates proper error."""
        error = permission_denied_error("/protected/file", "write_file")

        self.assertEqual(error.error_type, ToolErrorType.PERMISSION_DENIED)
        self.assertIn("/protected/file", error.message)
        self.assertFalse(error.recoverable)

    def test_syntax_error_factory(self):
        """syntax_error creates proper error."""
        error = syntax_error("Unexpected token", "src/parser.py", "code_gen")

        self.assertEqual(error.error_type, ToolErrorType.SYNTAX_ERROR)
        self.assertIn("Unexpected token", error.message)
        self.assertEqual(error.context["file_path"], "src/parser.py")
        self.assertTrue(error.recoverable)

    def test_timeout_error_factory(self):
        """timeout_error creates proper error."""
        error = timeout_error("Long running task", 60, "run_cmd")

        self.assertEqual(error.error_type, ToolErrorType.TIMEOUT)
        self.assertIn("Long running task", error.message)
        self.assertIn("60s", error.message)
        self.assertEqual(error.context["timeout"], 60)
        self.assertTrue(error.recoverable)

    def test_timeout_error_factory_without_timeout(self):
        """timeout_error works without timeout parameter."""
        error = timeout_error("Long running task", tool_name="run_cmd")

        self.assertEqual(error.error_type, ToolErrorType.TIMEOUT)
        self.assertIn("Long running task", error.message)
        self.assertIsNone(error.context.get("timeout"))

    def test_validation_error_factory(self):
        """validation_error creates proper error."""
        error = validation_error("Invalid type for 'count'", {"count": "not_a_number"})

        self.assertEqual(error.error_type, ToolErrorType.VALIDATION_ERROR)
        self.assertIn("Invalid type", error.message)
        self.assertEqual(error.context["invalid_params"]["count"], "not_a_number")
        self.assertTrue(error.recoverable)


class TestErrorIntegration(unittest.TestCase):
    """Test error taxonomy integration scenarios."""

    def test_error_recovery_roundtrip(self):
        """Error can be converted to dict and back."""
        original = ToolError(
            error_type=ToolErrorType.NOT_FOUND,
            message="File missing",
            context={"file": "test.py"},
            suggested_recovery=["Search"],
        )

        error_dict = original.to_dict()
        restored = ToolError.from_dict(error_dict)

        self.assertEqual(restored.error_type, original.error_type)
        self.assertEqual(restored.message, original.message)
        self.assertEqual(restored.context, original.context)
        self.assertEqual(restored.suggested_recovery, original.suggested_recovery)

    def test_all_error_types_are_distinct(self):
        """Each error type has unique value."""
        values = {e.value for e in ToolErrorType}
        self.assertEqual(len(values), len(ToolErrorType))

    def test_error_context_preserves_tool_name(self):
        """Tool name is preserved in context."""
        error = ToolError.from_exception(FileNotFoundError("x"), "my_custom_tool")
        self.assertEqual(error.context["tool"], "my_custom_tool")

    def test_error_with_file_path_context(self):
        """File path context is properly set."""
        error = syntax_error("Error", "/path/to/file.py")
        self.assertEqual(error.context["file_path"], "/path/to/file.py")


if __name__ == "__main__":
    unittest.main()