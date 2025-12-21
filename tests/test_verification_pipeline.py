#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for multi-stage verification pipeline."""

import pytest
from pathlib import Path
import tempfile
import shutil

from rev.execution.verification_pipeline import (
    VerificationPipeline,
    VerificationStage,
    RiskLevel,
    StageResult,
    VerificationResult,
    select_stages_for_task
)
from rev.models.task import Task


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    workspace = Path(tempfile.mkdtemp())
    yield workspace
    shutil.rmtree(workspace)


@pytest.fixture
def pipeline(temp_workspace):
    """Create a verification pipeline."""
    return VerificationPipeline(temp_workspace)


class TestStageSelection:
    """Test verification stage selection logic."""

    def test_low_risk_docs_only(self):
        """Low risk (docs only) should run syntax stage only."""
        task = Task(description="Update README.md", action_type="edit")
        file_paths = ["README.md", "docs/guide.md"]
        risk_level = RiskLevel.LOW

        stages = select_stages_for_task(task, file_paths, risk_level)

        assert stages == [VerificationStage.SYNTAX]

    def test_medium_risk_code_change(self):
        """Medium risk (code change) should run syntax + unit."""
        task = Task(description="Fix bug in utils.py", action_type="edit")
        file_paths = ["utils.py"]
        risk_level = RiskLevel.MEDIUM

        stages = select_stages_for_task(task, file_paths, risk_level)

        assert stages == [VerificationStage.SYNTAX, VerificationStage.UNIT]

    def test_high_risk_infra_change(self):
        """High risk (infra) should run syntax + unit + integration."""
        task = Task(description="Update orchestrator logic", action_type="edit")
        file_paths = ["rev/execution/orchestrator.py", "rev/tools/shell.py"]
        risk_level = RiskLevel.HIGH

        stages = select_stages_for_task(task, file_paths, risk_level)

        assert stages == [
            VerificationStage.SYNTAX,
            VerificationStage.UNIT,
            VerificationStage.INTEGRATION
        ]

    def test_behavioral_stage_added_when_specified(self):
        """Behavioral stage should be added when task specifies it."""
        task = Task(description="Add new feature", action_type="create")
        task.metadata = {"behavioral_test_cmd": "pytest tests/e2e/"}
        file_paths = ["feature.py"]
        risk_level = RiskLevel.MEDIUM

        stages = select_stages_for_task(task, file_paths, risk_level)

        assert VerificationStage.BEHAVIORAL in stages


class TestRiskAssessment:
    """Test risk assessment logic."""

    def test_docs_only_is_low_risk(self, pipeline):
        """Docs/config only should be low risk."""
        task = Task(description="Update docs", action_type="edit")
        file_paths = ["README.md", "config.yaml"]

        risk = pipeline._assess_risk(task, file_paths)

        assert risk == RiskLevel.LOW

    def test_single_code_file_is_medium_risk(self, pipeline):
        """Single code file change should be medium risk."""
        task = Task(description="Fix bug", action_type="edit")
        file_paths = ["utils.py"]

        risk = pipeline._assess_risk(task, file_paths)

        assert risk == RiskLevel.MEDIUM

    def test_multi_file_code_change_is_high_risk(self, pipeline):
        """Multi-file code change should be high risk."""
        task = Task(description="Refactor module", action_type="edit")
        file_paths = ["file1.py", "file2.py", "file3.py", "file4.py"]

        risk = pipeline._assess_risk(task, file_paths)

        assert risk == RiskLevel.HIGH

    def test_infra_keyword_triggers_high_risk(self, pipeline):
        """Infrastructure-related changes should be high risk."""
        task = Task(description="Update orchestrator", action_type="edit")
        file_paths = ["orchestrator.py"]

        risk = pipeline._assess_risk(task, file_paths)

        assert risk == RiskLevel.HIGH

    def test_tooling_file_triggers_high_risk(self, pipeline):
        """Changes to tooling files should be high risk."""
        task = Task(description="Fix tool", action_type="edit")
        file_paths = ["rev/tools/shell.py"]

        risk = pipeline._assess_risk(task, file_paths)

        assert risk == RiskLevel.HIGH


class TestSyntaxVerification:
    """Test syntax verification stage."""

    def test_valid_python_syntax_passes(self, pipeline, temp_workspace):
        """Valid Python syntax should pass."""
        test_file = temp_workspace / "valid.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        result = pipeline._verify_syntax(["valid.py"])

        assert result.passed
        assert result.stage == VerificationStage.SYNTAX
        assert "valid" in result.message.lower()

    def test_invalid_python_syntax_fails(self, pipeline, temp_workspace):
        """Invalid Python syntax should fail."""
        test_file = temp_workspace / "invalid.py"
        test_file.write_text("def hello(\n    return 'world'\n")  # Missing closing paren

        result = pipeline._verify_syntax(["invalid.py"])

        assert not result.passed
        assert result.stage == VerificationStage.SYNTAX
        assert "error" in result.message.lower()

    def test_no_python_files_skips(self, pipeline):
        """No Python files should skip syntax check."""
        result = pipeline._verify_syntax(["README.md", "config.yaml"])

        assert result.passed
        assert "no python files" in result.message.lower()

    def test_multiple_files_all_valid(self, pipeline, temp_workspace):
        """Multiple valid files should all pass."""
        (temp_workspace / "file1.py").write_text("x = 1\n")
        (temp_workspace / "file2.py").write_text("y = 2\n")

        result = pipeline._verify_syntax(["file1.py", "file2.py"])

        assert result.passed
        assert "2 file(s)" in result.message


class TestUnitTestVerification:
    """Test unit test verification stage."""

    def test_passing_unit_tests(self, pipeline, temp_workspace):
        """Passing unit tests should succeed."""
        # Create a simple test file
        tests_dir = temp_workspace / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_example.py"
        test_file.write_text("""
def test_simple():
    assert 1 + 1 == 2

def test_another():
    assert True
""")

        result = pipeline._verify_unit_tests(["tests/test_example.py"])

        assert result.passed
        assert result.stage == VerificationStage.UNIT
        assert "passed" in result.message.lower()

    def test_failing_unit_tests(self, pipeline, temp_workspace):
        """Failing unit tests should fail."""
        tests_dir = temp_workspace / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_fail.py"
        test_file.write_text("""
def test_fail():
    assert 1 + 1 == 3
""")

        result = pipeline._verify_unit_tests(["tests/test_fail.py"])

        assert not result.passed
        assert "failed" in result.message.lower()

    def test_no_test_files_skips(self, pipeline):
        """No test files should skip unit test stage."""
        result = pipeline._verify_unit_tests([])

        assert result.passed
        assert "no test files" in result.message.lower()
        assert result.details.get("skipped")


class TestIntegrationVerification:
    """Test integration test verification stage."""

    def test_no_integration_dir_skips(self, pipeline):
        """No integration test directory should skip."""
        result = pipeline._verify_integration(["some_file.py"])

        assert result.passed
        assert "no integration tests" in result.message.lower()
        assert result.details.get("skipped")

    def test_integration_tests_pass(self, pipeline, temp_workspace):
        """Passing integration tests should succeed."""
        integration_dir = temp_workspace / "tests" / "integration"
        integration_dir.mkdir(parents=True)
        test_file = integration_dir / "test_integration.py"
        test_file.write_text("""
def test_integration():
    assert True
""")

        result = pipeline._verify_integration(["some_file.py"])

        assert result.passed
        assert "passed" in result.message.lower()

    def test_integration_tests_fail(self, pipeline, temp_workspace):
        """Failing integration tests should fail."""
        integration_dir = temp_workspace / "tests" / "integration"
        integration_dir.mkdir(parents=True)
        test_file = integration_dir / "test_integration.py"
        test_file.write_text("""
def test_integration():
    assert False
""")

        result = pipeline._verify_integration(["some_file.py"])

        assert not result.passed
        assert "failed" in result.message.lower()


class TestBehavioralVerification:
    """Test behavioral test verification stage."""

    def test_no_behavioral_cmd_skips(self, pipeline):
        """No behavioral test command should skip."""
        task = Task(description="Test", action_type="edit")

        result = pipeline._verify_behavioral(task)

        assert result.passed
        assert "no behavioral test" in result.message.lower()
        assert result.details.get("skipped")

    def test_behavioral_cmd_success(self, pipeline):
        """Successful behavioral test command should pass."""
        task = Task(description="Test", action_type="edit")
        task.metadata = {"behavioral_test_cmd": "python --version"}

        result = pipeline._verify_behavioral(task)

        assert result.passed
        assert "passed" in result.message.lower()

    def test_behavioral_cmd_failure(self, pipeline):
        """Failing behavioral test command should fail."""
        task = Task(description="Test", action_type="edit")
        task.metadata = {"behavioral_test_cmd": "exit 1"}

        result = pipeline._verify_behavioral(task)

        assert not result.passed
        assert "failed" in result.message.lower()


class TestFullPipeline:
    """Test full verification pipeline execution."""

    def test_all_stages_pass(self, pipeline, temp_workspace):
        """All stages passing should result in overall pass."""
        # Create valid Python file
        test_file = temp_workspace / "example.py"
        test_file.write_text("def foo():\n    return 42\n")

        # Create passing test
        tests_dir = temp_workspace / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_example.py"
        test_file.write_text("""
def test_foo():
    assert True
""")

        task = Task(description="Add foo function to example.py", action_type="create")

        result = pipeline.verify(
            task,
            file_paths=["example.py"],
            required_stages=[VerificationStage.SYNTAX, VerificationStage.UNIT]
        )

        assert result.passed
        assert len(result.stages_run) == 2
        assert all(s.passed for s in result.stages_run)

    def test_syntax_failure_stops_pipeline(self, pipeline, temp_workspace):
        """Syntax failure should stop pipeline early."""
        # Create invalid Python file
        test_file = temp_workspace / "broken.py"
        test_file.write_text("def foo(\n    return 42\n")

        task = Task(description="Add broken function", action_type="create")

        result = pipeline.verify(
            task,
            file_paths=["broken.py"],
            required_stages=[VerificationStage.SYNTAX, VerificationStage.UNIT]
        )

        assert not result.passed
        # Should only run syntax stage (stop on first failure)
        assert len(result.stages_run) == 1
        assert result.stages_run[0].stage == VerificationStage.SYNTAX

    def test_unit_test_failure_fails_pipeline(self, pipeline, temp_workspace):
        """Unit test failure should fail pipeline."""
        # Create valid syntax file
        test_file = temp_workspace / "example.py"
        test_file.write_text("def foo():\n    return 42\n")

        # Create failing test
        tests_dir = temp_workspace / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_example.py"
        test_file.write_text("""
def test_foo():
    assert False
""")

        task = Task(description="Add foo function", action_type="create")

        result = pipeline.verify(
            task,
            file_paths=["example.py"],
            required_stages=[VerificationStage.SYNTAX, VerificationStage.UNIT]
        )

        assert not result.passed
        assert len(result.stages_run) == 2
        assert result.stages_run[0].passed  # Syntax passed
        assert not result.stages_run[1].passed  # Unit failed

    def test_auto_stage_selection_low_risk(self, pipeline):
        """Auto stage selection for low risk should only run syntax."""
        task = Task(description="Update README", action_type="edit")

        result = pipeline.verify(task, file_paths=["README.md"])

        assert result.risk_level == RiskLevel.LOW
        # Should auto-select only syntax stage
        assert len(result.stages_run) <= 1

    def test_auto_stage_selection_high_risk(self, pipeline, temp_workspace):
        """Auto stage selection for high risk should run multiple stages."""
        # Create valid files
        (temp_workspace / "orchestrator.py").write_text("x = 1\n")
        (temp_workspace / "tool.py").write_text("y = 2\n")
        (temp_workspace / "agent.py").write_text("z = 3\n")
        (temp_workspace / "pipeline.py").write_text("w = 4\n")

        task = Task(description="Update orchestrator", action_type="edit")

        result = pipeline.verify(
            task,
            file_paths=["orchestrator.py", "tool.py", "agent.py", "pipeline.py"]
        )

        assert result.risk_level == RiskLevel.HIGH
        # Should auto-select multiple stages
        assert len(result.stages_run) >= 2

    def test_verification_result_summary(self, pipeline, temp_workspace):
        """Verification result should produce readable summary."""
        test_file = temp_workspace / "example.py"
        test_file.write_text("def foo():\n    return 42\n")

        task = Task(description="Add foo", action_type="create")

        result = pipeline.verify(
            task,
            file_paths=["example.py"],
            required_stages=[VerificationStage.SYNTAX]
        )

        summary = result.summary()

        assert "Verification:" in summary
        assert "Risk Level:" in summary
        assert "Stages:" in summary


class TestFilePathExtraction:
    """Test file path extraction from tasks."""

    def test_extract_from_description(self, pipeline):
        """Should extract file paths from task description."""
        task = Task(
            description="Update utils.py and config.yaml",
            action_type="edit"
        )

        paths = pipeline._extract_file_paths(task)

        assert "utils.py" in paths
        assert "config.yaml" in paths

    def test_extract_from_tool_events(self, pipeline):
        """Should extract file paths from tool events."""
        task = Task(description="Edit files", action_type="edit")
        task.tool_events = [
            {"tool": "edit", "args": {"file_path": "example.py"}},
            {"tool": "create", "args": {"path": "new.py"}}
        ]

        paths = pipeline._extract_file_paths(task)

        assert "example.py" in paths
        assert "new.py" in paths


class TestTestFileDiscovery:
    """Test test file discovery logic."""

    def test_find_test_file_in_tests_dir(self, pipeline, temp_workspace):
        """Should find test file in tests/ directory."""
        # Create source and test files
        (temp_workspace / "utils.py").write_text("pass\n")
        tests_dir = temp_workspace / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_utils.py").write_text("pass\n")

        test_files = pipeline._find_test_files(["utils.py"])

        assert "tests/test_utils.py" in test_files

    def test_test_file_is_already_test(self, pipeline):
        """Test file should be returned as-is."""
        test_files = pipeline._find_test_files(["tests/test_example.py"])

        assert "tests/test_example.py" in test_files

    def test_no_test_file_found(self, pipeline, temp_workspace):
        """Should return empty list if no test file found."""
        (temp_workspace / "orphan.py").write_text("pass\n")

        test_files = pipeline._find_test_files(["orphan.py"])

        assert test_files == []
