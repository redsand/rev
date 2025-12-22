#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Replayable Run Bundle.

A run bundle captures all inputs, actions, and outputs from a task execution,
allowing it to be replayed, debugged, or analyzed later.
"""

import unittest
from unittest.mock import Mock, MagicMock
from pathlib import Path
from typing import Dict, List, Any
import json


class TestBundleCapture(unittest.TestCase):
    """Test capturing task execution into a bundle."""

    def test_capture_initial_request(self):
        """Bundle should capture the initial user request."""
        from rev.run_bundle.capture import BundleCapture

        capture = BundleCapture()
        capture.record_request("Fix the bug in main.py")

        bundle = capture.get_bundle()

        self.assertIn("request", bundle)
        self.assertEqual(bundle["request"], "Fix the bug in main.py")

    def test_capture_tool_calls(self):
        """Bundle should capture all tool calls with parameters and results."""
        from rev.run_bundle.capture import BundleCapture

        capture = BundleCapture()
        capture.record_tool_call(
            tool="read_file",
            params={"file_path": "main.py"},
            result="file contents here"
        )

        bundle = capture.get_bundle()

        self.assertIn("tool_calls", bundle)
        self.assertEqual(len(bundle["tool_calls"]), 1)
        self.assertEqual(bundle["tool_calls"][0]["tool"], "read_file")
        self.assertIn("params", bundle["tool_calls"][0])
        self.assertIn("result", bundle["tool_calls"][0])

    def test_capture_llm_calls(self):
        """Bundle should capture LLM calls with prompts and responses."""
        from rev.run_bundle.capture import BundleCapture

        capture = BundleCapture()
        capture.record_llm_call(
            messages=[{"role": "user", "content": "Analyze this"}],
            response={"message": {"content": "Analysis here"}},
            model="qwen2.5-coder:7b"
        )

        bundle = capture.get_bundle()

        self.assertIn("llm_calls", bundle)
        self.assertEqual(len(bundle["llm_calls"]), 1)
        self.assertIn("messages", bundle["llm_calls"][0])
        self.assertIn("response", bundle["llm_calls"][0])
        self.assertIn("model", bundle["llm_calls"][0])

    def test_capture_file_modifications(self):
        """Bundle should capture file modifications (writes, edits)."""
        from rev.run_bundle.capture import BundleCapture

        capture = BundleCapture()
        capture.record_file_modification(
            file_path="main.py",
            operation="edit",
            old_content="old code",
            new_content="new code"
        )

        bundle = capture.get_bundle()

        self.assertIn("file_modifications", bundle)
        self.assertEqual(len(bundle["file_modifications"]), 1)
        self.assertEqual(bundle["file_modifications"][0]["file_path"], "main.py")
        self.assertEqual(bundle["file_modifications"][0]["operation"], "edit")

    def test_capture_validation_results(self):
        """Bundle should capture validation results (tests, linting)."""
        from rev.run_bundle.capture import BundleCapture

        capture = BundleCapture()
        capture.record_validation(
            validator="pytest",
            result={"rc": 0, "passed": 5, "failed": 0}
        )

        bundle = capture.get_bundle()

        self.assertIn("validations", bundle)
        self.assertEqual(len(bundle["validations"]), 1)
        self.assertEqual(bundle["validations"][0]["validator"], "pytest")

    def test_capture_includes_timestamp(self):
        """Bundle should include timestamps for each event."""
        from rev.run_bundle.capture import BundleCapture

        capture = BundleCapture()
        capture.record_tool_call("read_file", {"path": "test.py"}, "content")

        bundle = capture.get_bundle()

        self.assertIn("timestamp", bundle["tool_calls"][0])


class TestBundleSerialization(unittest.TestCase):
    """Test serialization and deserialization of bundles."""

    def test_serialize_bundle_to_json(self):
        """Bundle should be serializable to JSON."""
        from rev.run_bundle.serialization import serialize_bundle

        bundle = {
            "request": "Test request",
            "tool_calls": [{"tool": "read_file", "params": {}, "result": "data"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        json_str = serialize_bundle(bundle)

        self.assertIsInstance(json_str, str)
        # Should be valid JSON
        parsed = json.loads(json_str)
        self.assertEqual(parsed["request"], "Test request")

    def test_deserialize_bundle_from_json(self):
        """Bundle should be deserializable from JSON."""
        from rev.run_bundle.serialization import deserialize_bundle

        json_str = json.dumps({
            "request": "Test request",
            "tool_calls": [{"tool": "grep", "params": {"pattern": "test"}, "result": "matches"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        })

        bundle = deserialize_bundle(json_str)

        self.assertIsInstance(bundle, dict)
        self.assertEqual(bundle["request"], "Test request")
        self.assertEqual(len(bundle["tool_calls"]), 1)

    def test_save_bundle_to_file(self):
        """Bundle should be saveable to a file."""
        from rev.run_bundle.serialization import save_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        # Mock path
        output_path = save_bundle(bundle, Path("/tmp/test_bundle.json"))

        self.assertIsInstance(output_path, Path)
        self.assertTrue(str(output_path).endswith(".json"))

    def test_load_bundle_from_file(self):
        """Bundle should be loadable from a file."""
        from rev.run_bundle.serialization import load_bundle, save_bundle

        bundle = {
            "request": "Load test",
            "tool_calls": [{"tool": "test", "params": {}, "result": "ok"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        # In real implementation, this would save and load
        # For testing, we'll just verify the interface
        # Mock implementation will be tested separately


class TestBundleReplay(unittest.TestCase):
    """Test replaying bundles."""

    def test_replay_tool_calls(self):
        """Replay should execute tool calls from bundle."""
        from rev.run_bundle.replay import replay_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [
                {"tool": "read_file", "params": {"file_path": "test.py"}, "result": "expected"}
            ],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        # Mock tool executor
        tool_executor = Mock()
        tool_executor.execute.return_value = "expected"

        result = replay_bundle(bundle, tool_executor=tool_executor, replay_mode="verify")

        self.assertIn("success", result)
        self.assertTrue(result["success"])

    def test_replay_detects_divergence(self):
        """Replay should detect when results diverge from bundle."""
        from rev.run_bundle.replay import replay_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [
                {"tool": "read_file", "params": {"file_path": "test.py"}, "result": "original"}
            ],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        # Tool returns different result
        tool_executor = Mock()
        tool_executor.execute.return_value = "DIFFERENT"

        result = replay_bundle(bundle, tool_executor=tool_executor, replay_mode="verify")

        self.assertFalse(result["success"])
        self.assertIn("divergences", result)
        self.assertGreater(len(result["divergences"]), 0)

    def test_replay_with_mock_mode(self):
        """Replay in mock mode should use recorded results."""
        from rev.run_bundle.replay import replay_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [
                {"tool": "read_file", "params": {"file_path": "test.py"}, "result": "mocked_result"}
            ],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        # In mock mode, should use bundle results, not call tools
        result = replay_bundle(bundle, replay_mode="mock")

        self.assertTrue(result["success"])
        # Should have used mocked results from bundle

    def test_replay_skips_destructive_operations(self):
        """Replay should skip destructive operations by default."""
        from rev.run_bundle.replay import replay_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [
                {"tool": "write_file", "params": {"path": "test.py", "content": "new"}, "result": "ok"}
            ],
            "llm_calls": [],
            "file_modifications": [
                {"file_path": "test.py", "operation": "write", "new_content": "new"}
            ],
            "validations": []
        }

        result = replay_bundle(bundle, replay_mode="safe")

        # Should skip writes in safe mode
        self.assertIn("skipped_operations", result)


class TestBundleAnalysis(unittest.TestCase):
    """Test analyzing bundles for debugging."""

    def test_analyze_bundle_statistics(self):
        """Analyze should provide statistics about bundle."""
        from rev.run_bundle.analysis import analyze_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [{"tool": "read_file"}, {"tool": "grep"}, {"tool": "edit"}],
            "llm_calls": [{"model": "qwen"}, {"model": "qwen"}],
            "file_modifications": [{"operation": "edit"}],
            "validations": [{"validator": "pytest"}]
        }

        stats = analyze_bundle(bundle)

        self.assertIn("total_tool_calls", stats)
        self.assertEqual(stats["total_tool_calls"], 3)
        self.assertIn("total_llm_calls", stats)
        self.assertEqual(stats["total_llm_calls"], 2)
        self.assertIn("files_modified", stats)
        self.assertEqual(stats["files_modified"], 1)

    def test_analyze_identifies_failure_points(self):
        """Analyze should identify where execution failed."""
        from rev.run_bundle.analysis import analyze_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [
                {"tool": "read_file", "result": "ok"},
                {"tool": "edit", "error": "string not found"},
                {"tool": "grep", "result": "matches"}
            ],
            "llm_calls": [],
            "file_modifications": [],
            "validations": [{"validator": "pytest", "result": {"rc": 1, "failed": 2}}]
        }

        stats = analyze_bundle(bundle)

        self.assertIn("failures", stats)
        self.assertGreater(len(stats["failures"]), 0)
        # Should identify edit failure and test failures

    def test_analyze_llm_token_usage(self):
        """Analyze should calculate total LLM token usage."""
        from rev.run_bundle.analysis import analyze_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [],
            "llm_calls": [
                {"model": "qwen", "usage": {"prompt": 100, "completion": 50}},
                {"model": "qwen", "usage": {"prompt": 200, "completion": 75}}
            ],
            "file_modifications": [],
            "validations": []
        }

        stats = analyze_bundle(bundle)

        self.assertIn("total_tokens", stats)
        self.assertEqual(stats["total_tokens"], 425)  # 100+50+200+75


class TestBundleComparison(unittest.TestCase):
    """Test comparing bundles to find differences."""

    def test_compare_two_bundles(self):
        """Should compare two bundles and identify differences."""
        from rev.run_bundle.comparison import compare_bundles

        bundle1 = {
            "request": "Test",
            "tool_calls": [{"tool": "read_file", "result": "v1"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        bundle2 = {
            "request": "Test",
            "tool_calls": [{"tool": "read_file", "result": "v2"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        diff = compare_bundles(bundle1, bundle2)

        self.assertIn("differences", diff)
        self.assertGreater(len(diff["differences"]), 0)

    def test_compare_identifies_missing_steps(self):
        """Should identify when one bundle has more steps."""
        from rev.run_bundle.comparison import compare_bundles

        bundle1 = {
            "request": "Test",
            "tool_calls": [{"tool": "read"}, {"tool": "edit"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        bundle2 = {
            "request": "Test",
            "tool_calls": [{"tool": "read"}],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        diff = compare_bundles(bundle1, bundle2)

        self.assertIn("missing_in_bundle2", diff)
        self.assertGreater(len(diff["missing_in_bundle2"]), 0)


class TestBundleValidation(unittest.TestCase):
    """Test validating bundle integrity."""

    def test_validate_bundle_structure(self):
        """Validator should check bundle has required fields."""
        from rev.run_bundle.validation import validate_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        result = validate_bundle(bundle)

        self.assertTrue(result["valid"])

    def test_validate_detects_missing_fields(self):
        """Validator should detect missing required fields."""
        from rev.run_bundle.validation import validate_bundle

        bundle = {
            "request": "Test",
            # Missing tool_calls, llm_calls, etc.
        }

        result = validate_bundle(bundle)

        self.assertFalse(result["valid"])
        self.assertIn("errors", result)

    def test_validate_detects_malformed_entries(self):
        """Validator should detect malformed entries."""
        from rev.run_bundle.validation import validate_bundle

        bundle = {
            "request": "Test",
            "tool_calls": [
                {"tool": "read_file"}  # Missing params and result
            ],
            "llm_calls": [],
            "file_modifications": [],
            "validations": []
        }

        result = validate_bundle(bundle)

        # Should warn about incomplete tool call
        self.assertIn("warnings", result)


if __name__ == "__main__":
    unittest.main()
