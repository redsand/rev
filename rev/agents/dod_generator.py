#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DoD Generator Agent.

Generates Definition of Done specifications for tasks using LLM.
"""

from typing import Optional, List
import json
import re

from rev.models.task import Task
from rev.models.dod import (
    DefinitionOfDone,
    Deliverable,
    DeliverableType,
    ValidationStage
)
from rev.llm.client import ollama_chat


def generate_dod(task: Task, user_request: str) -> DefinitionOfDone:
    """
    Generate a Definition of Done specification for a task.

    Uses LLM to analyze the task and user request, then generates concrete
    deliverables, acceptance criteria, and required validation stages.

    Args:
        task: The task to generate DoD for
        user_request: The original user request

    Returns:
        DefinitionOfDone specification

    Raises:
        ValueError: If LLM fails to generate valid DoD
    """
    prompt = _build_dod_generation_prompt(task, user_request)

    response = ollama_chat([{"role": "user", "content": prompt}])

    if "error" in response:
        raise ValueError(f"LLM error generating DoD: {response.get('error')}")

    content = response.get("message", {}).get("content", "")
    if not content:
        raise ValueError("Empty response from LLM")

    dod = _parse_dod_from_llm_response(content, task)
    return dod


def _build_dod_generation_prompt(task: Task, user_request: str) -> str:
    """Build the prompt for DoD generation."""
    return f"""You are a Definition of Done (DoD) generator. Your job is to create a concrete, measurable DoD specification for a task.

USER REQUEST:
{user_request}

TASK:
- ID: {task.task_id if hasattr(task, 'task_id') else 'unknown'}
- Description: {task.description}
- Action Type: {task.action_type}

Generate a Definition of Done with the following:

1. DELIVERABLES - Concrete outputs the task must produce:
   - file_modified: Files that will be changed
   - file_created: New files that will be created
   - test_pass: Tests that must pass
   - syntax_valid: Files that must have valid syntax
   - runtime_check: Commands that must run successfully
   - imports_work: Modules that must be importable

2. ACCEPTANCE CRITERIA - Specific conditions that must be true:
   - Observable facts (e.g., "pytest exit code == 0")
   - Measurable outcomes (e.g., "auto-registration count == 34")
   - No subjective criteria

3. VALIDATION STAGES - Which verification stages are required:
   - syntax: Always required for code changes
   - unit: Required when changing logic
   - integration: Required for multi-file changes
   - behavioral: Required for user-facing features

OUTPUT FORMAT (JSON):
{{
  "deliverables": [
    {{
      "type": "file_modified",
      "description": "Update analyst registry in main.py",
      "path": "main.py"
    }},
    {{
      "type": "test_pass",
      "description": "All unit tests pass",
      "command": "pytest tests/ -q"
    }}
  ],
  "acceptance_criteria": [
    "pytest exit code == 0",
    "no syntax errors in modified files",
    "auto-registration works correctly"
  ],
  "validation_stages": ["syntax", "unit"]
}}

IMPORTANT:
- Be specific (use exact file paths, commands)
- Be measurable (use concrete conditions)
- Focus on THIS task only (not the entire project)
- Include minimal sufficient validation (don't over-engineer)

Generate the DoD now (JSON only, no explanation):"""


def _parse_dod_from_llm_response(content: str, task: Task) -> DefinitionOfDone:
    """Parse DoD from LLM response."""
    # Extract JSON from response (might be wrapped in markdown code blocks)
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to parse entire content as JSON
        json_str = content.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLM response as JSON: {e}\n\nContent:\n{content}")

    # Parse deliverables
    deliverables = []
    for d_data in data.get("deliverables", []):
        try:
            deliverable_type = DeliverableType(d_data["type"])
        except (ValueError, KeyError):
            # Skip invalid deliverable types
            continue

        deliverable = Deliverable(
            type=deliverable_type,
            description=d_data.get("description", ""),
            path=d_data.get("path"),
            paths=d_data.get("paths"),
            command=d_data.get("command"),
            expect=d_data.get("expect")
        )
        deliverables.append(deliverable)

    # Parse acceptance criteria
    acceptance_criteria = data.get("acceptance_criteria", [])
    if not isinstance(acceptance_criteria, list):
        acceptance_criteria = []

    # Parse validation stages
    validation_stages = []
    for stage_str in data.get("validation_stages", []):
        try:
            stage = ValidationStage(stage_str)
            validation_stages.append(stage)
        except ValueError:
            # Skip invalid stages
            continue

    # Always include syntax stage for code changes
    if task.action_type in ["edit", "create", "refactor"] and ValidationStage.SYNTAX not in validation_stages:
        validation_stages.insert(0, ValidationStage.SYNTAX)

    # Create DoD
    task_id = getattr(task, 'task_id', f"task_{id(task)}")

    return DefinitionOfDone(
        task_id=task_id,
        description=task.description,
        deliverables=deliverables,
        acceptance_criteria=acceptance_criteria,
        validation_stages=validation_stages
    )


def _extract_file_paths_from_task(task: Task) -> List[str]:
    """Extract file paths from task description or tool events."""
    paths = []

    # Extract from description using common patterns
    desc = task.description.lower()

    # Pattern 1: "file.py" or "path/to/file.py"
    file_pattern = r'\b[\w/\\.-]+\.(?:py|js|ts|jsx|tsx|java|cpp|c|h|go|rs|rb|php)\b'
    matches = re.findall(file_pattern, task.description)
    paths.extend(matches)

    # Extract from tool events if available
    if hasattr(task, 'tool_events') and task.tool_events:
        for event in task.tool_events:
            if isinstance(event, dict):
                args = event.get('args', {})
                for key in ['path', 'file_path', 'target']:
                    if key in args and isinstance(args[key], str):
                        paths.append(args[key])

    # Deduplicate
    return list(set(paths))


def generate_simple_dod(task: Task) -> DefinitionOfDone:
    """
    Generate a simple fallback DoD when LLM is unavailable.

    Uses heuristics based on task action type.

    Args:
        task: The task to generate DoD for

    Returns:
        Basic DefinitionOfDone specification
    """
    task_id = getattr(task, 'task_id', f"task_{id(task)}")
    deliverables = []
    acceptance_criteria = []
    validation_stages = []

    # Extract file paths from task description/events
    file_paths = _extract_file_paths_from_task(task)

    # Heuristics based on action type
    if task.action_type == "edit":
        for path in file_paths:
            deliverables.append(Deliverable(
                type=DeliverableType.FILE_MODIFIED,
                description=f"File modified: {path}",
                path=path,
                metadata={"inferred": True}
            ))
        if not file_paths:
            # Fallback without specific path
            deliverables.append(Deliverable(
                type=DeliverableType.SYNTAX_VALID,
                description="Modified files are syntactically valid",
                metadata={"inferred": True}
            ))
        acceptance_criteria.append("file syntax is valid")
        validation_stages.append(ValidationStage.SYNTAX)

    elif task.action_type == "create":
        deliverables.append(Deliverable(
            type=DeliverableType.FILE_CREATED,
            description="File created successfully",
            metadata={"inferred": True}
        ))
        acceptance_criteria.append("file exists and is not empty")
        validation_stages.append(ValidationStage.SYNTAX)

    elif task.action_type == "test":
        deliverables.append(Deliverable(
            type=DeliverableType.TEST_PASS,
            description="Tests pass",
            command="pytest",
            metadata={"inferred": True}
        ))
        acceptance_criteria.append("pytest exit code == 0")
        validation_stages.append(ValidationStage.UNIT)

    else:
        # Generic fallback
        deliverables.append(Deliverable(
            type=DeliverableType.SYNTAX_VALID,
            description="Code is syntactically valid",
            metadata={"inferred": True}
        ))
        acceptance_criteria.append("no syntax errors")
        validation_stages.append(ValidationStage.SYNTAX)

    return DefinitionOfDone(
        task_id=task_id,
        description=task.description,
        deliverables=deliverables,
        acceptance_criteria=acceptance_criteria,
        validation_stages=validation_stages,
        metadata={"generated_by": "simple_heuristic"}
    )
