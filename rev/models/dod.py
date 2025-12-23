#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Definition of Done (DoD) models.

Each task has a DoD that specifies concrete deliverables and acceptance criteria.
The DoD acts as a hard gate - verification must satisfy all criteria or the task fails.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import yaml


class DeliverableType(Enum):
    """Types of deliverables a task can produce."""
    FILE_MODIFIED = "file_modified"
    FILE_CREATED = "file_created"
    FILE_DELETED = "file_deleted"
    TEST_PASS = "test_pass"
    SYNTAX_VALID = "syntax_valid"
    RUNTIME_CHECK = "runtime_check"
    IMPORTS_WORK = "imports_work"
    NO_REGRESSION = "no_regression"
    API_ROUTE_CHECK = "api_route_check"
    CURL_SMOKE_TEST = "curl_smoke_test"
    PLAYWRIGHT_TEST = "playwright_test"


class ValidationStage(Enum):
    """Verification stages that can be required."""
    SYNTAX = "syntax"
    UNIT = "unit"
    INTEGRATION = "integration"
    BEHAVIORAL = "behavioral"


@dataclass
class Deliverable:
    """A concrete deliverable that a task must produce."""
    type: DeliverableType
    description: str
    path: Optional[str] = None
    paths: Optional[List[str]] = None
    command: Optional[str] = None
    expect: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result = {
            "type": self.type.value,
            "description": self.description
        }
        if self.path:
            result["path"] = self.path
        if self.paths:
            result["paths"] = self.paths
        if self.command:
            result["command"] = self.command
        if self.expect:
            result["expect"] = self.expect
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Deliverable":
        """Deserialize from dictionary."""
        return Deliverable(
            type=DeliverableType(data["type"]),
            description=data["description"],
            path=data.get("path"),
            paths=data.get("paths"),
            command=data.get("command"),
            expect=data.get("expect"),
            metadata=data.get("metadata", {})
        )


@dataclass
class DefinitionOfDone:
    """
    Definition of Done specification for a task.

    Defines concrete deliverables, acceptance criteria, and validation stages
    that must be satisfied before a task can be marked as complete.
    """
    task_id: str
    description: str
    deliverables: List[Deliverable]
    acceptance_criteria: List[str]
    validation_stages: List[ValidationStage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_yaml(self) -> str:
        """Serialize to YAML format."""
        data = {
            "task_id": self.task_id,
            "description": self.description,
            "deliverables": [d.to_dict() for d in self.deliverables],
            "acceptance_criteria": self.acceptance_criteria,
            "validation_stages": [s.value for s in self.validation_stages],
        }
        if self.metadata:
            data["metadata"] = self.metadata

        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @staticmethod
    def from_yaml(yaml_str: str) -> "DefinitionOfDone":
        """Deserialize from YAML format."""
        data = yaml.safe_load(yaml_str)

        deliverables = [Deliverable.from_dict(d) for d in data.get("deliverables", [])]
        validation_stages = [ValidationStage(s) for s in data.get("validation_stages", [])]

        return DefinitionOfDone(
            task_id=data["task_id"],
            description=data["description"],
            deliverables=deliverables,
            acceptance_criteria=data.get("acceptance_criteria", []),
            validation_stages=validation_stages,
            metadata=data.get("metadata", {})
        )

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"DoD({self.task_id}): {len(self.deliverables)} deliverables, "
            f"{len(self.acceptance_criteria)} criteria, "
            f"{len(self.validation_stages)} stages"
        )
