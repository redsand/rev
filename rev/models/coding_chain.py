#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coding Chain models for structured multi-stage coding workflows.

This module implements the Prompt Chaining pattern from Agentic Design Patterns,
specifically tailored for deep coding workflows: analysis → design → plan →
implement → test → refine.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class CodingStageType(Enum):
    """Types of stages in a coding workflow."""
    ANALYSIS = "analysis"  # Understand requirement, affected modules
    DESIGN = "design"      # Architectural approach, file-level impact
    PLAN = "plan"          # Generate or refine ExecutionPlan tasks
    IMPLEMENT = "implement"  # Per-task code changes
    TEST = "test"          # Decide test commands, add tests if missing
    REFINE = "refine"      # Handle test failures & review feedback
    DOCUMENT = "document"  # Update documentation


class StageStatus(Enum):
    """Status of a coding stage."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class CodingStage:
    """A single stage in a coding workflow chain.

    Each stage represents a distinct phase with its own prompt, inputs,
    and outputs that feed into the next stage.
    """
    name: str  # "analysis", "design", "plan", "implement", "test", "refine"
    stage_type: CodingStageType
    status: StageStatus = StageStatus.PENDING
    notes: List[str] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # Names of prerequisite stages
    skippable: bool = False  # Can this stage be skipped?

    def add_note(self, note: str):
        """Add a note to this stage."""
        self.notes.append(note)

    def add_artifact(self, key: str, value: Any):
        """Add an artifact produced by this stage."""
        self.artifacts[key] = value

    def mark_completed(self):
        """Mark this stage as completed."""
        self.status = StageStatus.COMPLETED

    def mark_failed(self, reason: str):
        """Mark this stage as failed."""
        self.status = StageStatus.FAILED
        self.add_note(f"Failed: {reason}")

    def mark_skipped(self, reason: str = None):
        """Mark this stage as skipped."""
        self.status = StageStatus.SKIPPED
        if reason:
            self.add_note(f"Skipped: {reason}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "stage_type": self.stage_type.value,
            "status": self.status.value,
            "notes": self.notes,
            "artifacts": self.artifacts,
            "dependencies": self.dependencies,
            "skippable": self.skippable
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodingStage':
        """Create from dictionary."""
        return cls(
            name=data["name"],
            stage_type=CodingStageType(data["stage_type"]),
            status=StageStatus(data.get("status", "pending")),
            notes=data.get("notes", []),
            artifacts=data.get("artifacts", {}),
            dependencies=data.get("dependencies", []),
            skippable=data.get("skippable", False)
        )


@dataclass
class CodingWorkflow:
    """A complete coding workflow with multiple stages.

    This implements the Prompt Chaining pattern by breaking down complex
    coding tasks into explicit, sequential stages with clear inputs/outputs.
    """
    stages: List[CodingStage] = field(default_factory=list)
    user_request: str = ""
    workflow_type: str = "standard"  # standard, quick_edit, full_feature, refactor

    def add_stage(
        self,
        name: str,
        stage_type: CodingStageType,
        dependencies: List[str] = None,
        skippable: bool = False
    ) -> CodingStage:
        """Add a stage to the workflow."""
        stage = CodingStage(
            name=name,
            stage_type=stage_type,
            dependencies=dependencies or [],
            skippable=skippable
        )
        self.stages.append(stage)
        return stage

    def current_stage(self) -> Optional[CodingStage]:
        """Get the current stage (first non-completed stage)."""
        for stage in self.stages:
            if stage.status not in [StageStatus.COMPLETED, StageStatus.SKIPPED]:
                return stage
        return None

    def get_stage(self, name: str) -> Optional[CodingStage]:
        """Get a stage by name."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        return None

    def is_complete(self) -> bool:
        """Check if all required stages are complete."""
        return all(
            stage.status in [StageStatus.COMPLETED, StageStatus.SKIPPED]
            for stage in self.stages
        )

    def get_summary(self) -> str:
        """Get a human-readable summary of workflow progress."""
        completed = sum(1 for s in self.stages if s.status == StageStatus.COMPLETED)
        total = len(self.stages)
        current = self.current_stage()

        summary_parts = [f"Coding Workflow: {completed}/{total} stages completed"]
        if current:
            summary_parts.append(f"Current stage: {current.name} ({current.stage_type.value})")

        return " | ".join(summary_parts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "stages": [s.to_dict() for s in self.stages],
            "user_request": self.user_request,
            "workflow_type": self.workflow_type
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CodingWorkflow':
        """Create from dictionary."""
        workflow = cls(
            stages=[CodingStage.from_dict(s) for s in data.get("stages", [])],
            user_request=data.get("user_request", ""),
            workflow_type=data.get("workflow_type", "standard")
        )
        return workflow

    @classmethod
    def create_standard_workflow(cls, user_request: str) -> 'CodingWorkflow':
        """Create a standard coding workflow with all stages.

        Stages:
          1. Analysis - understand requirements and affected modules
          2. Design - architectural approach and file-level impact
          3. Plan - generate detailed task breakdown
          4. Implement - execute code changes
          5. Test - run tests and validate
          6. Refine - handle failures and feedback
          7. Document - update docs (optional)
        """
        workflow = cls(user_request=user_request, workflow_type="standard")

        workflow.add_stage("analysis", CodingStageType.ANALYSIS)
        workflow.add_stage("design", CodingStageType.DESIGN, dependencies=["analysis"])
        workflow.add_stage("plan", CodingStageType.PLAN, dependencies=["design"])
        workflow.add_stage("implement", CodingStageType.IMPLEMENT, dependencies=["plan"])
        workflow.add_stage("test", CodingStageType.TEST, dependencies=["implement"])
        workflow.add_stage("refine", CodingStageType.REFINE, dependencies=["test"], skippable=True)
        workflow.add_stage("document", CodingStageType.DOCUMENT, dependencies=["implement"], skippable=True)

        return workflow

    @classmethod
    def create_quick_edit_workflow(cls, user_request: str) -> 'CodingWorkflow':
        """Create a quick edit workflow for simple changes.

        Stages:
          1. Analysis - quick understanding
          2. Implement - make changes
          3. Test - validate
        """
        workflow = cls(user_request=user_request, workflow_type="quick_edit")

        workflow.add_stage("analysis", CodingStageType.ANALYSIS)
        workflow.add_stage("implement", CodingStageType.IMPLEMENT, dependencies=["analysis"])
        workflow.add_stage("test", CodingStageType.TEST, dependencies=["implement"])

        return workflow

    @classmethod
    def create_full_feature_workflow(cls, user_request: str) -> 'CodingWorkflow':
        """Create a comprehensive workflow for major features.

        This is similar to standard but with mandatory documentation.
        """
        workflow = cls.create_standard_workflow(user_request)
        workflow.workflow_type = "full_feature"

        # Make documentation non-skippable
        doc_stage = workflow.get_stage("document")
        if doc_stage:
            doc_stage.skippable = False

        return workflow

    @classmethod
    def create_refactor_workflow(cls, user_request: str) -> 'CodingWorkflow':
        """Create a workflow optimized for refactoring.

        Stages:
          1. Analysis - understand current structure
          2. Design - plan refactoring approach
          3. Implement - execute refactoring
          4. Test - ensure no regressions
          5. Document - update docs
        """
        workflow = cls(user_request=user_request, workflow_type="refactor")

        workflow.add_stage("analysis", CodingStageType.ANALYSIS)
        workflow.add_stage("design", CodingStageType.DESIGN, dependencies=["analysis"])
        workflow.add_stage("implement", CodingStageType.IMPLEMENT, dependencies=["design"])
        workflow.add_stage("test", CodingStageType.TEST, dependencies=["implement"])
        workflow.add_stage("document", CodingStageType.DOCUMENT, dependencies=["implement"])

        return workflow
