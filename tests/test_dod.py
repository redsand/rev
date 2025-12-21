#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Definition of Done (DoD) feature."""

import pytest
import tempfile
from pathlib import Path
import subprocess

from rev.models.task import Task
from rev.models.dod import (
    DefinitionOfDone,
    Deliverable,
    DeliverableType,
    ValidationStage
)
from rev.agents.dod_generator import generate_simple_dod, _parse_dod_from_llm_response
from rev.execution.dod_verifier import (
    verify_dod,
    DeliverableVerificationResult,
    _verify_file_modified,
    _verify_file_created,
    _verify_test_pass,
    _verify_syntax_valid
)


class TestDoDModels:
    """Test DoD model classes."""

    def test_deliverable_serialization(self):
        """Test deliverable to/from dict conversion."""
        deliverable = Deliverable(
            type=DeliverableType.FILE_MODIFIED,
            description="Update main.py",
            path="main.py"
        )

        # Serialize
        data = deliverable.to_dict()
        assert data["type"] == "file_modified"
        assert data["description"] == "Update main.py"
        assert data["path"] == "main.py"

        # Deserialize
        restored = Deliverable.from_dict(data)
        assert restored.type == DeliverableType.FILE_MODIFIED
        assert restored.description == "Update main.py"
        assert restored.path == "main.py"

    def test_dod_yaml_serialization(self):
        """Test DoD YAML serialization and deserialization."""
        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test task",
            deliverables=[
                Deliverable(
                    type=DeliverableType.FILE_MODIFIED,
                    description="Modify file",
                    path="test.py"
                )
            ],
            acceptance_criteria=["file exists", "syntax valid"],
            validation_stages=[ValidationStage.SYNTAX, ValidationStage.UNIT]
        )

        # Serialize to YAML
        yaml_str = dod.to_yaml()
        assert "task_id: T-001" in yaml_str
        assert "file_modified" in yaml_str
        assert "syntax" in yaml_str

        # Deserialize from YAML
        restored = DefinitionOfDone.from_yaml(yaml_str)
        assert restored.task_id == "T-001"
        assert restored.description == "Test task"
        assert len(restored.deliverables) == 1
        assert restored.deliverables[0].type == DeliverableType.FILE_MODIFIED
        assert len(restored.acceptance_criteria) == 2
        assert len(restored.validation_stages) == 2

    def test_dod_repr(self):
        """Test DoD string representation."""
        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test",
            deliverables=[Deliverable(type=DeliverableType.SYNTAX_VALID, description="Check syntax")],
            acceptance_criteria=["no errors"],
            validation_stages=[ValidationStage.SYNTAX]
        )

        repr_str = repr(dod)
        assert "T-001" in repr_str
        assert "1 deliverables" in repr_str
        assert "1 criteria" in repr_str
        assert "1 stages" in repr_str


class TestDoDGenerator:
    """Test DoD generation."""

    def test_generate_simple_dod_for_edit_task(self):
        """Test simple DoD generation for edit task."""
        task = Task(description="Fix bug in utils.py", action_type="edit")

        dod = generate_simple_dod(task)

        assert dod.description == "Fix bug in utils.py"
        assert len(dod.deliverables) >= 1
        assert dod.deliverables[0].type == DeliverableType.FILE_MODIFIED
        assert ValidationStage.SYNTAX in dod.validation_stages
        assert "syntax" in dod.acceptance_criteria[0].lower()

    def test_generate_simple_dod_for_create_task(self):
        """Test simple DoD generation for create task."""
        task = Task(description="Create new module", action_type="create")

        dod = generate_simple_dod(task)

        assert len(dod.deliverables) >= 1
        assert dod.deliverables[0].type == DeliverableType.FILE_CREATED
        assert ValidationStage.SYNTAX in dod.validation_stages

    def test_generate_simple_dod_for_test_task(self):
        """Test simple DoD generation for test task."""
        task = Task(description="Run tests", action_type="test")

        dod = generate_simple_dod(task)

        assert len(dod.deliverables) >= 1
        assert dod.deliverables[0].type == DeliverableType.TEST_PASS
        assert ValidationStage.UNIT in dod.validation_stages
        assert "pytest" in dod.deliverables[0].command

    def test_parse_dod_from_llm_json_response(self):
        """Test parsing DoD from LLM JSON response."""
        task = Task(description="Test task", action_type="edit")
        llm_response = """
        {
          "deliverables": [
            {
              "type": "file_modified",
              "description": "Update main.py",
              "path": "main.py"
            },
            {
              "type": "test_pass",
              "description": "Tests pass",
              "command": "pytest -q"
            }
          ],
          "acceptance_criteria": [
            "pytest exit code == 0",
            "no syntax errors"
          ],
          "validation_stages": ["syntax", "unit"]
        }
        """

        dod = _parse_dod_from_llm_response(llm_response, task)

        assert len(dod.deliverables) == 2
        assert dod.deliverables[0].type == DeliverableType.FILE_MODIFIED
        assert dod.deliverables[1].type == DeliverableType.TEST_PASS
        assert len(dod.acceptance_criteria) == 2
        assert len(dod.validation_stages) == 2

    def test_parse_dod_from_markdown_wrapped_json(self):
        """Test parsing DoD from markdown code block."""
        task = Task(description="Test task", action_type="edit")
        llm_response = """
        Here is the DoD:
        ```json
        {
          "deliverables": [
            {"type": "file_modified", "description": "Update file", "path": "test.py"}
          ],
          "acceptance_criteria": ["file exists"],
          "validation_stages": ["syntax"]
        }
        ```
        """

        dod = _parse_dod_from_llm_response(llm_response, task)

        assert len(dod.deliverables) == 1
        assert dod.deliverables[0].path == "test.py"

    def test_parse_dod_auto_adds_syntax_stage_for_code_changes(self):
        """Test that syntax stage is automatically added for code changes."""
        task = Task(description="Edit code", action_type="edit")
        llm_response = """
        {
          "deliverables": [{"type": "file_modified", "description": "Update file", "path": "test.py"}],
          "acceptance_criteria": ["file exists"],
          "validation_stages": ["unit"]
        }
        """

        dod = _parse_dod_from_llm_response(llm_response, task)

        # Syntax should be auto-added as first stage
        assert ValidationStage.SYNTAX in dod.validation_stages
        assert dod.validation_stages[0] == ValidationStage.SYNTAX


class TestDoDVerifier:
    """Test DoD verification."""

    def test_verify_file_modified_succeeds_when_file_exists(self, tmp_path):
        """Test file modified verification succeeds when file exists."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("print('hello')")

        deliverable = Deliverable(
            type=DeliverableType.FILE_MODIFIED,
            description="Modify test.py",
            path="test.py"
        )

        task = Task(description="Test", action_type="edit")
        task.tool_events = [
            {"tool": "replace_in_file", "args": {"path": "test.py"}}
        ]

        result = _verify_file_modified(deliverable, task, tmp_path)

        assert result.passed
        assert "test.py" in result.message

    def test_verify_file_modified_fails_when_file_missing(self, tmp_path):
        """Test file modified verification fails when file doesn't exist."""
        deliverable = Deliverable(
            type=DeliverableType.FILE_MODIFIED,
            description="Modify missing.py",
            path="missing.py"
        )

        task = Task(description="Test", action_type="edit")

        result = _verify_file_modified(deliverable, task, tmp_path)

        assert not result.passed
        assert "does not exist" in result.message

    def test_verify_file_created_succeeds_when_file_exists_and_not_empty(self, tmp_path):
        """Test file created verification succeeds when file exists and has content."""
        test_file = tmp_path / "new_file.py"
        test_file.write_text("content")

        deliverable = Deliverable(
            type=DeliverableType.FILE_CREATED,
            description="Create new_file.py",
            path="new_file.py"
        )

        task = Task(description="Test", action_type="create")

        result = _verify_file_created(deliverable, task, tmp_path)

        assert result.passed

    def test_verify_file_created_fails_when_file_empty(self, tmp_path):
        """Test file created verification fails when file is empty."""
        test_file = tmp_path / "empty.py"
        test_file.touch()  # Create empty file

        deliverable = Deliverable(
            type=DeliverableType.FILE_CREATED,
            description="Create empty.py",
            path="empty.py"
        )

        task = Task(description="Test", action_type="create")

        result = _verify_file_created(deliverable, task, tmp_path)

        assert not result.passed
        assert "empty" in result.message.lower()

    def test_verify_test_pass_succeeds_when_command_succeeds(self, tmp_path):
        """Test test pass verification succeeds when command returns 0."""
        deliverable = Deliverable(
            type=DeliverableType.TEST_PASS,
            description="Run echo test",
            command="python -c \"print('test')\"",
            expect="exit_code == 0"
        )

        task = Task(description="Test", action_type="test")

        result = _verify_test_pass(deliverable, task, tmp_path)

        assert result.passed
        assert "passed" in result.message.lower()

    def test_verify_test_pass_fails_when_command_fails(self, tmp_path):
        """Test test pass verification fails when command returns non-zero."""
        deliverable = Deliverable(
            type=DeliverableType.TEST_PASS,
            description="Run failing test",
            command="python -c \"import sys; sys.exit(1)\"",
            expect="exit_code == 0"
        )

        task = Task(description="Test", action_type="test")

        result = _verify_test_pass(deliverable, task, tmp_path)

        assert not result.passed
        assert "failed" in result.message.lower()

    def test_verify_syntax_valid_succeeds_for_valid_python(self, tmp_path):
        """Test syntax validation succeeds for valid Python file."""
        test_file = tmp_path / "valid.py"
        test_file.write_text("def foo():\n    return 42\n")

        deliverable = Deliverable(
            type=DeliverableType.SYNTAX_VALID,
            description="Check syntax",
            path="valid.py"
        )

        task = Task(description="Test", action_type="edit")

        result = _verify_syntax_valid(deliverable, task, tmp_path)

        assert result.passed

    def test_verify_syntax_valid_fails_for_invalid_python(self, tmp_path):
        """Test syntax validation fails for invalid Python file."""
        test_file = tmp_path / "invalid.py"
        test_file.write_text("def foo(\n    # Missing closing paren\n")

        deliverable = Deliverable(
            type=DeliverableType.SYNTAX_VALID,
            description="Check syntax",
            path="invalid.py"
        )

        task = Task(description="Test", action_type="edit")

        result = _verify_syntax_valid(deliverable, task, tmp_path)

        assert not result.passed
        assert "syntax error" in result.message.lower()

    def test_verify_dod_passes_when_all_criteria_met(self, tmp_path):
        """Test complete DoD verification passes when all criteria met."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def foo():\n    return 42\n")

        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test task",
            deliverables=[
                Deliverable(
                    type=DeliverableType.FILE_MODIFIED,
                    description="Modify test.py",
                    path="test.py"
                ),
                Deliverable(
                    type=DeliverableType.SYNTAX_VALID,
                    description="Valid syntax",
                    path="test.py"
                )
            ],
            acceptance_criteria=["no syntax errors"],
            validation_stages=[ValidationStage.SYNTAX]
        )

        task = Task(description="Test", action_type="edit")
        task.tool_events = [
            {"tool": "replace_in_file", "args": {"path": "test.py"}}
        ]

        result = verify_dod(dod, task, tmp_path)

        assert result.passed
        assert len(result.deliverable_results) == 2
        assert all(r.passed for r in result.deliverable_results)
        assert not result.unmet_criteria

    def test_verify_dod_fails_when_deliverable_unmet(self, tmp_path):
        """Test DoD verification fails when deliverable is unmet."""
        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test task",
            deliverables=[
                Deliverable(
                    type=DeliverableType.FILE_CREATED,
                    description="Create missing.py",
                    path="missing.py"
                )
            ],
            acceptance_criteria=[],
            validation_stages=[]
        )

        task = Task(description="Test", action_type="create")

        result = verify_dod(dod, task, tmp_path)

        assert not result.passed
        assert len(result.unmet_criteria) > 0

    def test_dod_verification_result_summary(self, tmp_path):
        """Test DoD verification result summary generation."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1")

        dod = DefinitionOfDone(
            task_id="T-001",
            description="Test",
            deliverables=[
                Deliverable(
                    type=DeliverableType.FILE_MODIFIED,
                    description="Modify file",
                    path="test.py"
                )
            ],
            acceptance_criteria=["file exists"],
            validation_stages=[]
        )

        task = Task(description="Test", action_type="edit")
        task.tool_events = [{"tool": "edit", "args": {"path": "test.py"}}]

        result = verify_dod(dod, task, tmp_path)
        summary = result.summary()

        assert "DoD Verification" in summary
        assert "Deliverables" in summary
        assert "passed" in summary.lower()


class TestDoDIntegration:
    """Integration tests for DoD feature."""

    def test_full_workflow_edit_task(self, tmp_path):
        """Test full DoD workflow for an edit task."""
        # 1. Create task
        task = Task(description="Fix function in utils.py", action_type="edit")

        # 2. Generate DoD
        dod = generate_simple_dod(task)
        assert len(dod.deliverables) > 0
        assert len(dod.validation_stages) > 0

        # 3. Simulate task execution
        test_file = tmp_path / "utils.py"
        test_file.write_text("def fixed_function():\n    return True\n")

        task.tool_events = [
            {"tool": "replace_in_file", "args": {"path": "utils.py"}}
        ]

        # 4. Verify DoD
        result = verify_dod(dod, task, tmp_path)

        assert result.passed
        assert all(r.passed for r in result.deliverable_results)

    def test_full_workflow_create_task_with_tests(self, tmp_path):
        """Test full DoD workflow for a create task with tests."""
        # 1. Create task
        task = Task(description="Create new module with tests", action_type="create")

        # 2. Generate DoD with test requirement
        dod = DefinitionOfDone(
            task_id="T-002",
            description="Create module",
            deliverables=[
                Deliverable(
                    type=DeliverableType.FILE_CREATED,
                    description="Create module.py",
                    path="module.py"
                ),
                Deliverable(
                    type=DeliverableType.SYNTAX_VALID,
                    description="Valid syntax",
                    path="module.py"
                ),
                Deliverable(
                    type=DeliverableType.TEST_PASS,
                    description="Tests pass",
                    command="python -c \"print('tests pass')\""
                )
            ],
            acceptance_criteria=["pytest exit code == 0"],
            validation_stages=[ValidationStage.SYNTAX, ValidationStage.UNIT]
        )

        # 3. Simulate task execution
        module_file = tmp_path / "module.py"
        module_file.write_text("class MyClass:\n    pass\n")

        task.tool_events = [
            {"tool": "write_file", "args": {"path": "module.py"}}
        ]

        # 4. Verify DoD
        result = verify_dod(dod, task, tmp_path)

        assert result.passed
        assert all(r.passed for r in result.deliverable_results)

    def test_workflow_fails_gracefully_on_unmet_criteria(self, tmp_path):
        """Test DoD verification fails gracefully with clear error messages."""
        task = Task(description="Incomplete task", action_type="edit")

        dod = DefinitionOfDone(
            task_id="T-003",
            description="Task with unmet criteria",
            deliverables=[
                Deliverable(
                    type=DeliverableType.FILE_CREATED,
                    description="Create file that doesn't exist",
                    path="nonexistent.py"
                )
            ],
            acceptance_criteria=["file must exist and be valid"],
            validation_stages=[]
        )

        result = verify_dod(dod, task, tmp_path)

        assert not result.passed
        assert len(result.unmet_criteria) > 0
        assert "nonexistent.py" in result.summary()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
