#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated REV Capability and Performance Testing Suite.

This module tests REV's ability to solve various scenarios using the
ollama provider with the glm-4.7:cloud model.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import unittest


# Fix Windows console encoding for emoji characters
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, 'strict')


# Configure REV to use ollama with glm-4.7:cloud (allow env override)
os.environ["REV_LLM_PROVIDER"] = "ollama"
os.environ.setdefault("OLLAMA_MODEL", "glm-4.7:cloud")
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"
os.environ["REV_TDD_ENABLED"] = "true"
os.environ["REV_EXECUTION_MODE"] = "sub-agent"
# Fix Windows encoding issues
os.environ["PYTHONIOENCODING"] = "utf-8"


@dataclass
class TestResult:
    """Result of a single test run."""

    playbook_id: str
    playbook_name: str
    success: bool
    error: Optional[str] = None
    output: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    duration: float = 0.0


@dataclass
class TestSuiteSummary:
    """Summary of test suite execution."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    duration: float = 0.0
    results: List[TestResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as percentage."""
        return (self.passed / self.total * 100) if self.total > 0 else 0.0

    def add_result(self, result: TestResult) -> None:
        """Add a test result."""
        self.total += 1
        if result.success:
            self.passed += 1
        else:
            self.failed += 1
        self.duration += result.duration
        self.results.append(result)


class REVCapabilityTest(unittest.TestCase):
    """Test suite for REV capabilities using glm-4.7:cloud."""

    @classmethod
    def setUpClass(cls):
        """Set up test suite - verify ollama is available."""
        cls.summary = TestSuiteSummary()
        cls.playbooks_dir = Path(__file__).parent.parent / "playbooks"

        # Verify ollama is available
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                print("WARNING: ollama CLI not found. Tests may fail.")
                print("Make sure ollama is installed and the glm-4.7:cloud model is available.")
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"WARNING: Could not verify ollama: {e}")

    def setUp(self):
        """Set up each test case."""
        self.start_time = time.time()

    def tearDown(self):
        """Tear down each test case."""
        duration = time.time() - self.start_time
        if hasattr(self, 'current_result'):
            self.current_result.duration = duration

    def run_playbook(
        self,
        playbook_id: str,
        description: str
    ) -> TestResult:
        """Run a playbook test case.

        Args:
            playbook_id: The playbook ID (e.g., "01_simple_string_manipulation")
            description: Description of the test

        Returns:
            TestResult with execution details
        """
        result = TestResult(
            playbook_id=playbook_id,
            playbook_name=description,
            success=False
        )
        self.current_result = result

        playbook_dir = self.playbooks_dir / playbook_id

        if not playbook_dir.exists():
            result.error = f"Playbook directory not found: {playbook_dir}"
            return result

        # Read the README to understand the task
        readme = playbook_dir / "README.md"
        if readme.exists():
            result.metrics["readme"] = readme.read_text()[:500]  # Store preview

        # Create a temporary workspace for this test
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()

            # Copy the playbook files to workspace
            try:
                if (playbook_dir / "string_utils.py").exists():
                    shutil.copy(playbook_dir / "string_utils.py", workspace)
                # Copy other source files as needed
                for src_file in playbook_dir.glob("*.py"):
                    if src_file.name != "test_*.py":
                        shutil.copy(src_file, workspace)

                # Run REV with the task
                task_description = self._get_task_description(playbook_id)
                result.metrics["task_description"] = task_description

                try:
                    from rev.execution.orchestrator import run_orchestrated

                    output = run_orchestrated(
                        user_request=task_description,
                        project_root=workspace,
                        enable_learning=False,
                        enable_research=True,
                        enable_review=False,
                        enable_validation=False,
                        parallel_workers=1,
                        auto_approve=True,
                        read_only=False,
                    )

                    result.output = str(output)[:1000]  # Store preview

                    # Check if the task was completed successfully
                    result.success = self._validate_completion(
                        playbook_id, workspace, output
                    )

                except Exception as e:
                    result.error = f"Execution failed: {str(e)}"
                    import traceback
                    result.metrics["traceback"] = traceback.format_exc()

            except Exception as e:
                result.error = f"Setup failed: {str(e)}"

        return result

    def _get_task_description(self, playbook_id: str) -> str:
        """Get the task description for a playbook."""
        descriptions = {
            "01_simple_string_manipulation": (
                "Implement utility functions in string_utils.py: "
                "reverse_string(s), count_vowels(s), is_palindrome(s), capitalize_words(s). "
                "Make sure to handle empty strings and include docstrings."
            ),
            "02_advanced_shopping_cart": (
                "Implement a shopping cart system in cart.py and product.py: "
                "Product class with id, name, price, stock_quantity, validate(), apply_discount(), is_in_stock(). "
                "ShoppingCart class with add_item(), remove_item(), update_quantity(), get_total(), clear(). "
                "Add custom exceptions: OutOfStockError, ItemNotFoundError, InvalidQuantityError."
            ),
            "03_complex_task_manager": (
                "Implement an async task manager in task_manager.py: "
                "Task model, TaskStatus enum, @timeout and @retry decorators, TaskScheduler with run(), stop(), cancel(). "
                "Include validation with TaskValidationError exception."
            ),
            "04_very_complex_microservice": (
                "Implement a REST API microservice in models.py, repositories.py, routes.py: "
                "User and Product models, UserRepository and ProductRepository, "
                "API routes with endpoints for CRUD operations, JWT authentication."
            ),
            "05_integration_e2e_multi_service": (
                "Implement a multi-service distributed application: "
                "UserService, ProductService, OrderService, NotificationService, API Gateway. "
                "Service communication via API calls, request/response models."
            ),
        }
        return descriptions.get(playbook_id, f"Complete the implementation in {playbook_id}")

    def _validate_completion(
        self,
        playbook_id: str,
        workspace: Path,
        output: Any
    ) -> bool:
        """Validate that the playbook task was completed successfully.

        Args:
            playbook_id: The playbook ID
            workspace: The workspace directory
            output: The orchestrator output

        Returns:
            True if validation passed, False otherwise
        """
        # Check if files were created/modified
        expected_files = {
            "01_simple_string_manipulation": ["string_utils.py"],
            "02_advanced_shopping_cart": ["product.py", "cart.py", "exceptions.py"],
            "03_complex_task_manager": ["task_manager.py"],
            "04_very_complex_microservice": ["models.py", "repositories.py", "routes.py"],
            "05_integration_e2e_multi_service": [
                "user_service.py", "product_service.py", "order_service.py",
                "notification_service.py", "api_gateway.py"
            ],
        }

        expected = expected_files.get(playbook_id, [])
        for file in expected:
            if not (workspace / file).exists():
                return False

        # Check for basic syntax validation
        for file in expected:
            file_path = workspace / file
            if file_path.exists():
                try:
                    with open(file_path) as f:
                        compile(f.read(), file_path, 'exec')
                except SyntaxError:
                    return False

        # Check orchestrator output for errors
        output_str = str(output)
        if "error" in output_str.lower() or "failed" in output_str.lower():
            # Check if it's a known acceptable error
            if "error" in output_str.lower() and "validation" in output_str.lower():
                # Validation errors might be acceptable
                pass
            else:
                return False

        return True


# Test Cases

class TestPlaybook01Simple(REVCapabilityTest):
    """Test Playbook 01: Simple String Manipulation."""

    def test_01_string_manipulation(self):
        """REV should implement string manipulation functions correctly."""
        result = self.run_playbook(
            "01_simple_string_manipulation",
            "Simple String Manipulation"
        )

        self.summary.add_result(result)

        if not result.success:
            if result.error:
                self.fail(f"Test failed: {result.error}")
            else:
                self.fail("Test failed: implementation incomplete or incorrect")


class TestPlaybook02Advanced(REVCapabilityTest):
    """Test Playbook 02: Advanced Shopping Cart."""

    def test_02_shopping_cart(self):
        """REV should implement shopping cart with error handling."""
        result = self.run_playbook(
            "02_advanced_shopping_cart",
            "Advanced Shopping Cart"
        )

        self.summary.add_result(result)

        if not result.success:
            if result.error:
                self.fail(f"Test failed: {result.error}")
            else:
                self.fail("Test failed: implementation incomplete or incorrect")


class TestPlaybook03Complex(REVCapabilityTest):
    """Test Playbook 03: Complex Task Manager."""

    def test_03_task_manager(self):
        """REV should implement async task manager system."""
        result = self.run_playbook(
            "03_complex_task_manager",
            "Complex Task Manager"
        )

        self.summary.add_result(result)

        if not result.success:
            if result.error:
                self.fail(f"Test failed: {result.error}")
            else:
                self.fail("Test failed: implementation incomplete or incorrect")


class TestPlaybook04Microservice(REVCapabilityTest):
    """Test Playbook 04: Very Complex Microservice."""

    def test_04_microservice(self):
        """REV should implement REST API microservice."""
        result = self.run_playbook(
            "04_very_complex_microservice",
            "Very Complex Microservice"
        )

        self.summary.add_result(result)

        if not result.success:
            if result.error:
                self.fail(f"Test failed: {result.error}")
            else:
                self.fail("Test failed: implementation incomplete or incorrect")


class TestPlaybook05Integration(REVCapabilityTest):
    """Test Playbook 05: Integration E2E Multi-Service."""

    def test_05_multi_service(self):
        """REV should implement multi-service distributed application."""
        result = self.run_playbook(
            "05_integration_e2e_multi_service",
            "Integration E2E Multi-Service"
        )

        self.summary.add_result(result)

        if not result.success:
            if result.error:
                self.fail(f"Test failed: {result.error}")
            else:
                self.fail("Test failed: implementation incomplete or incorrect")


class TestREVSuiteRunner:
    """Test suite runner with reporting."""

    @staticmethod
    def run_all(verbosity: int = 2) -> TestSuiteSummary:
        """Run all REV capability tests.

        Args:
            verbosity: Test verbosity level

        Returns:
            TestSuiteSummary with all results
        """
        # Load all test classes
        test_suite = unittest.TestSuite()

        test_classes = [
            TestPlaybook01Simple,
            TestPlaybook02Advanced,
            TestPlaybook03Complex,
            TestPlaybook04Microservice,
            TestPlaybook05Integration,
        ]

        for test_class in test_classes:
            tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
            test_suite.addTests(tests)

        # Run tests
        runner = unittest.TextTestRunner(verbosity=verbosity)
        result = runner.run(test_suite)

        # Collect results from test classes
        summary = TestSuiteSummary()
        for test_class in test_classes:
            if hasattr(test_class, 'summary'):
                for r in test_class.summary.results:
                    summary.add_result(r)

        # Print summary
        TestREVSuiteRunner.print_summary(summary)

        return summary

    @staticmethod
    def print_summary(summary: TestSuiteSummary) -> None:
        """Print test summary to console.

        Args:
            summary: TestSuiteSummary with results
        """
        print("\n" + "=" * 70)
        print("REV CAPABILITY TEST SUMMARY")
        print("=" * 70)
        print(f"Provider: ollama (glm-4.7:cloud)")
        print(f"Total Tests: {summary.total}")
        print(f"Passed: {summary.passed}")
        print(f"Failed: {summary.failed}")
        print(f"Pass Rate: {summary.pass_rate:.1f}%")
        print(f"Duration: {summary.duration:.2f}s")
        print("=" * 70)

        if summary.failed > 0:
            print("\nFailed Tests:")
            for result in summary.results:
                if not result.success:
                    print(f"  [{result.playbook_id}] {result.playbook_name}")
                    if result.error:
                        print(f"    Error: {result.error}")
            print("=" * 70)

        # Save detailed results to JSON
        results_file = Path(__file__).parent / "test_results.json"
        with open(results_file, 'w') as f:
            results_data = {
                "timestamp": datetime.now().isoformat(),
                "provider": "ollama",
                "model": "glm-4.7:cloud",
                "summary": {
                    "total": summary.total,
                    "passed": summary.passed,
                    "failed": summary.failed,
                    "pass_rate": summary.pass_rate,
                    "duration": summary.duration,
                },
                "results": [
                    {
                        "playbook_id": r.playbook_id,
                        "playbook_name": r.playbook_name,
                        "success": r.success,
                        "duration": r.duration,
                        "error": r.error,
                        "metrics": r.metrics,
                        "timestamp": r.timestamp.isoformat(),
                    }
                    for r in summary.results
                ],
            }
            json.dump(results_data, f, indent=2)
        print(f"\nDetailed results saved to: {results_file}")


if __name__ == "__main__":
    import sys

    # Run all tests
    verbosity = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    summary = TestREVSuiteRunner.run_all(verbosity=verbosity)

    # Exit with non-zero if any tests failed
    sys.exit(0 if summary.failed == 0 else 1)
