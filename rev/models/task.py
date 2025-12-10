#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task and plan models for rev."""

import re
import threading
from enum import Enum
from typing import Dict, Any, List, Optional


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class RiskLevel(Enum):
    """Risk levels for tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Task:
    """Represents a single task in the execution plan."""
    def __init__(self, description: str, action_type: str = "general", dependencies: List[int] = None):
        self.description = description
        self.action_type = action_type  # edit, add, delete, rename, test, review
        self.status = TaskStatus.PENDING
        self.result = None
        self.error = None
        self.dependencies = dependencies or []  # List of task indices this task depends on
        self.task_id = None  # Will be set when added to plan

        # Advanced planning features
        self.risk_level = RiskLevel.LOW  # Risk assessment
        self.risk_reasons = []  # List of reasons for risk level
        self.impact_scope = []  # List of files/modules affected
        self.estimated_changes = 0  # Estimated number of lines/files changed
        self.breaking_change = False  # Whether this might break existing functionality
        self.rollback_plan = None  # Rollback instructions if things go wrong
        self.validation_steps = []  # Steps to validate task completion
        self.complexity = "low"  # Task complexity: low, medium, high
        self.subtasks = []  # For complex tasks, list of subtask IDs
        self.priority = 0  # Task priority: higher values = more important (0 = normal)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "action_type": self.action_type,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "dependencies": self.dependencies,
            "task_id": self.task_id,
            "risk_level": self.risk_level.value,
            "risk_reasons": self.risk_reasons,
            "impact_scope": self.impact_scope,
            "estimated_changes": self.estimated_changes,
            "breaking_change": self.breaking_change,
            "rollback_plan": self.rollback_plan,
            "validation_steps": self.validation_steps,
            "complexity": self.complexity,
            "subtasks": self.subtasks,
            "priority": self.priority
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create a Task from a dictionary."""
        task = cls(
            description=data["description"],
            action_type=data.get("action_type", "general"),
            dependencies=data.get("dependencies", [])
        )
        task.status = TaskStatus(data["status"])
        task.result = data.get("result")
        task.error = data.get("error")
        task.task_id = data.get("task_id")
        task.risk_level = RiskLevel(data.get("risk_level", "low"))
        task.risk_reasons = data.get("risk_reasons", [])
        task.impact_scope = data.get("impact_scope", [])
        task.estimated_changes = data.get("estimated_changes", 0)
        task.breaking_change = data.get("breaking_change", False)
        task.rollback_plan = data.get("rollback_plan")
        task.validation_steps = data.get("validation_steps", [])
        task.complexity = data.get("complexity", "low")
        task.subtasks = data.get("subtasks", [])
        task.priority = data.get("priority", 0)
        return task


class ExecutionPlan:
    """Manages the task checklist for iterative execution with dependency tracking."""
    def __init__(self):
        self.tasks: List[Task] = []
        self.current_index = 0
        self.lock = threading.Lock()  # Thread-safe operations
        self.goals: List = []  # List of Goal objects for goal-oriented execution

    def add_task(self, description: str, action_type: str = "general", dependencies: List[int] = None):
        task = Task(description, action_type, dependencies)
        task.task_id = len(self.tasks)
        self.tasks.append(task)

    def get_current_task(self) -> Optional[Task]:
        """Get the next task (for sequential execution compatibility)."""
        if self.current_index < len(self.tasks):
            return self.tasks[self.current_index]
        return None

    def get_executable_tasks(self, max_count: int = 1) -> List[Task]:
        """Get tasks that are ready to execute (all dependencies met).

        This includes both PENDING and STOPPED tasks for resume functionality.
        Tasks are sorted by priority (higher priority first), then by task_id.
        """
        with self.lock:
            executable = []
            for task in self.tasks:
                # Include both PENDING and STOPPED tasks
                if task.status not in [TaskStatus.PENDING, TaskStatus.STOPPED]:
                    continue

                # Validate dependencies first
                for dep_id in task.dependencies:
                    if dep_id < 0 or dep_id >= len(self.tasks):
                        raise ValueError(f"Task {task.task_id} has invalid dependency: {dep_id}")

                # Check if all dependencies are completed
                deps_met = all(
                    self.tasks[dep_id].status == TaskStatus.COMPLETED
                    for dep_id in task.dependencies
                )

                if deps_met:
                    executable.append(task)

            # Sort by priority (descending) then by task_id (ascending)
            executable.sort(key=lambda t: (-t.priority, t.task_id))

            # Return up to max_count
            return executable[:max_count]

    def mark_task_in_progress(self, task: Task):
        """Mark a task as in progress."""
        with self.lock:
            task.status = TaskStatus.IN_PROGRESS

    def mark_task_completed(self, task: Task, result: str = None):
        """Mark a specific task as completed."""
        with self.lock:
            task.status = TaskStatus.COMPLETED
            task.result = result

    def mark_task_failed(self, task: Task, error: str):
        """Mark a specific task as failed."""
        with self.lock:
            task.status = TaskStatus.FAILED
            task.error = error

    def mark_completed(self, result: str = None):
        """Legacy method for sequential execution compatibility."""
        if self.current_index < len(self.tasks):
            self.tasks[self.current_index].status = TaskStatus.COMPLETED
            self.tasks[self.current_index].result = result
            self.current_index += 1

    def mark_failed(self, error: str):
        """Legacy method for sequential execution compatibility."""
        if self.current_index < len(self.tasks):
            self.tasks[self.current_index].status = TaskStatus.FAILED
            self.tasks[self.current_index].error = error

    def is_complete(self) -> bool:
        """Check if all tasks are done (completed or failed)."""
        return all(
            task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            for task in self.tasks
        )

    def has_pending_tasks(self) -> bool:
        """Check if there are any pending, in-progress, or stopped tasks."""
        return any(
            task.status in [TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.STOPPED]
            for task in self.tasks
        )

    def get_summary(self) -> str:
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)
        in_progress = sum(1 for t in self.tasks if t.status == TaskStatus.IN_PROGRESS)
        stopped = sum(1 for t in self.tasks if t.status == TaskStatus.STOPPED)
        total = len(self.tasks)

        parts = [f"{completed}/{total} completed"]
        if failed > 0:
            parts.append(f"{failed} failed")
        if in_progress > 0:
            parts.append(f"{in_progress} in progress")
        if stopped > 0:
            parts.append(f"{stopped} stopped")

        return f"Progress: {', '.join(parts)}"

    def analyze_dependencies(self) -> Dict[str, Any]:
        """Analyze task dependencies and create optimal ordering.

        Returns:
            Dict with dependency graph, execution order, and parallel opportunities
        """
        dependency_graph = {}
        reverse_deps = {}  # Which tasks depend on each task

        for task in self.tasks:
            task_id = task.task_id
            dependency_graph[task_id] = task.dependencies.copy()

            # Build reverse dependency map
            for dep_id in task.dependencies:
                if dep_id not in reverse_deps:
                    reverse_deps[dep_id] = []
                reverse_deps[dep_id].append(task_id)

        # Find tasks with no dependencies (can start immediately)
        root_tasks = [t.task_id for t in self.tasks if not t.dependencies]

        # Find critical path (longest chain of dependencies)
        def get_depth(task_id, visited=None):
            if visited is None:
                visited = set()
            if task_id in visited:
                return 0
            visited.add(task_id)

            if task_id >= len(self.tasks):
                return 0

            deps = self.tasks[task_id].dependencies
            if not deps:
                return 1
            return 1 + max(get_depth(dep_id, visited.copy()) for dep_id in deps)

        critical_path = []
        max_depth = 0
        for task in self.tasks:
            depth = get_depth(task.task_id)
            if depth > max_depth:
                max_depth = depth
                critical_path = [task.task_id]

        # Find parallelizable tasks (tasks at same depth level with no interdependencies)
        parallel_groups = []
        processed = set()

        for depth in range(max_depth):
            group = []
            for task in self.tasks:
                if task.task_id in processed:
                    continue
                task_depth = get_depth(task.task_id)
                if task_depth == depth + 1:
                    group.append(task.task_id)
                    processed.add(task.task_id)
            if group:
                parallel_groups.append(group)

        return {
            "dependency_graph": dependency_graph,
            "reverse_dependencies": reverse_deps,
            "root_tasks": root_tasks,
            "critical_path_length": max_depth,
            "parallel_groups": parallel_groups,
            "total_tasks": len(self.tasks),
            "parallelization_potential": sum(len(g) for g in parallel_groups if len(g) > 1)
        }

    def assess_impact(self, task: Task) -> Dict[str, Any]:
        """Assess the potential impact of a task.

        Args:
            task: The task to assess

        Returns:
            Dict with impact analysis including affected files, dependencies, etc.
        """
        impact = {
            "task_id": task.task_id,
            "description": task.description,
            "action_type": task.action_type,
            "affected_files": [],
            "affected_modules": [],
            "dependent_tasks": [],
            "estimated_scope": "unknown"
        }

        # Analyze based on action type
        if task.action_type == "delete":
            impact["estimated_scope"] = "high"
            impact["warning"] = "Destructive operation - data loss possible"
        elif task.action_type in ["edit", "add"]:
            impact["estimated_scope"] = "medium"
        elif task.action_type in ["review", "test"]:
            impact["estimated_scope"] = "low"

        # Find dependent tasks
        for other_task in self.tasks:
            if task.task_id in other_task.dependencies:
                impact["dependent_tasks"].append({
                    "task_id": other_task.task_id,
                    "description": other_task.description
                })

        # Extract file patterns from description
        file_patterns = re.findall(r'(?:in |to |for |file |module )[\w/.-]+\.[a-z]+', task.description.lower())
        impact["affected_files"] = list(set(file_patterns))

        # Estimate affected modules from description
        module_patterns = re.findall(r'(?:in |to |for )(\w+)(?:\s+module| package| service)', task.description.lower())
        impact["affected_modules"] = list(set(module_patterns))

        return impact

    def evaluate_risk(self, task: Task) -> RiskLevel:
        """Evaluate the risk level of a task.

        Args:
            task: The task to evaluate

        Returns:
            RiskLevel enum value
        """
        risk_score = 0
        task.risk_reasons = []

        # Risk factors

        # 1. Action type risk
        action_risks = {
            "delete": 3,
            "edit": 2,
            "add": 1,
            "rename": 2,
            "test": 0,
            "review": 0
        }
        action_risk = action_risks.get(task.action_type, 1)
        risk_score += action_risk

        if action_risk >= 2:
            task.risk_reasons.append(f"Destructive/modifying action: {task.action_type}")

        # 2. Keywords indicating risk
        high_risk_keywords = [
            "database", "schema", "migration", "production", "deploy",
            "auth", "security", "password", "token", "api key",
            "config", "configuration", "settings"
        ]

        desc_lower = task.description.lower()
        for keyword in high_risk_keywords:
            if keyword in desc_lower:
                risk_score += 1
                task.risk_reasons.append(f"High-risk component: {keyword}")
                break

        # 3. Scope of changes
        if any(word in desc_lower for word in ["all", "entire", "whole", "every"]):
            risk_score += 1
            task.risk_reasons.append("Wide scope of changes")

        # 4. Breaking changes indicators
        breaking_indicators = ["breaking", "incompatible", "remove support", "deprecate"]
        if any(indicator in desc_lower for indicator in breaking_indicators):
            risk_score += 2
            task.breaking_change = True
            task.risk_reasons.append("Potentially breaking change")

        # 5. Dependencies
        if len(task.dependencies) > 3:
            risk_score += 1
            task.risk_reasons.append(f"Many dependencies ({len(task.dependencies)})")

        # Map score to risk level
        if risk_score >= 5:
            return RiskLevel.CRITICAL
        elif risk_score >= 3:
            return RiskLevel.HIGH
        elif risk_score >= 1:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def create_rollback_plan(self, task: Task) -> str:
        """Create a rollback plan for a task.

        Args:
            task: The task to create rollback plan for

        Returns:
            String describing rollback procedure
        """
        rollback_steps = []

        # Action-specific rollback
        if task.action_type == "add":
            rollback_steps.append("Delete the newly created files")
            rollback_steps.append("Run: git clean -fd (after review)")

        elif task.action_type == "edit":
            rollback_steps.append("Revert changes using: git checkout -- <files>")
            rollback_steps.append("Or apply inverse patch")

        elif task.action_type == "delete":
            rollback_steps.append("⚠️  CRITICAL: Deleted files cannot be recovered without backup")
            rollback_steps.append("Restore from git history: git checkout HEAD~1 -- <files>")
            rollback_steps.append("Or restore from backup if available")

        elif task.action_type == "rename":
            rollback_steps.append("Rename files back to original names")
            rollback_steps.append("Update imports and references")

        # General rollback steps
        rollback_steps.append("")
        rollback_steps.append("General rollback procedure:")
        rollback_steps.append("1. Stop any running services")
        rollback_steps.append("2. Revert code changes: git reset --hard HEAD")
        rollback_steps.append("3. If changes were committed: git revert <commit-hash>")
        rollback_steps.append("4. Run tests to verify rollback: pytest / npm test")
        rollback_steps.append("5. Review logs for any issues")

        # Database rollback
        if "database" in task.description.lower() or "migration" in task.description.lower():
            rollback_steps.append("")
            rollback_steps.append("Database rollback:")
            rollback_steps.append("1. Run down migration: alembic downgrade -1")
            rollback_steps.append("2. Or restore from database backup")
            rollback_steps.append("3. Verify data integrity")

        return "\n".join(rollback_steps)

    def generate_validation_steps(self, task: Task) -> List[str]:
        """Generate validation steps for a task.

        Args:
            task: The task to generate validation for

        Returns:
            List of validation steps
        """
        steps = []

        # Common validation
        steps.append("Check for syntax errors")

        if task.action_type in ["add", "edit"]:
            steps.append("Run linter to check code quality")
            steps.append("Verify imports and dependencies")

        if task.action_type in ["add", "edit", "delete", "rename"]:
            steps.append("Run test suite: pytest / npm test")
            steps.append("Check for failing tests")

        # Specific validations
        if "api" in task.description.lower():
            steps.append("Test API endpoints manually or with integration tests")
            steps.append("Verify response formats and status codes")

        if "database" in task.description.lower():
            steps.append("Run database migrations")
            steps.append("Verify schema changes")
            steps.append("Check data integrity")

        if "security" in task.description.lower():
            steps.append("Run security scanner: bandit / npm audit")
            steps.append("Check for exposed secrets")

        if task.action_type == "delete":
            steps.append("Verify no references to deleted code remain")
            steps.append("Check import statements")
            steps.append("Run full test suite")

        steps.append("Review git diff for unintended changes")

        return steps

    def to_dict(self) -> Dict[str, Any]:
        goals_data = []
        for goal in self.goals:
            if hasattr(goal, 'to_dict'):
                goals_data.append(goal.to_dict())

        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "current_index": self.current_index,
            "summary": self.get_summary(),
            "goals": goals_data
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExecutionPlan':
        """Create an ExecutionPlan from a dictionary."""
        plan = cls()
        plan.tasks = [Task.from_dict(t) for t in data["tasks"]]
        plan.current_index = data.get("current_index", 0)

        # Load goals if present (lazy import to avoid circular dependency)
        goals_data = data.get("goals", [])
        if goals_data:
            try:
                from rev.models.goal import Goal
                plan.goals = [Goal.from_dict(g) for g in goals_data]
            except ImportError:
                plan.goals = []

        return plan

    def mark_task_stopped(self, task: Task):
        """Mark a specific task as stopped (for resume functionality)."""
        with self.lock:
            task.status = TaskStatus.STOPPED

    def save_checkpoint(self, filepath: str = None):
        """Save the current execution state to a checkpoint file.

        Args:
            filepath: Path to save checkpoint. If None, uses default location.
        """
        import json
        import os
        from datetime import datetime

        if filepath is None:
            checkpoint_dir = ".rev_checkpoints"
            os.makedirs(checkpoint_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(checkpoint_dir, f"checkpoint_{timestamp}.json")

        checkpoint_data = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "plan": self.to_dict()
        }

        with open(filepath, "w") as f:
            json.dump(checkpoint_data, f, indent=2)

        return filepath

    @classmethod
    def load_checkpoint(cls, filepath: str) -> 'ExecutionPlan':
        """Load an execution plan from a checkpoint file.

        Args:
            filepath: Path to the checkpoint file

        Returns:
            ExecutionPlan restored from checkpoint
        """
        import json

        with open(filepath, "r") as f:
            checkpoint_data = json.load(f)

        plan = cls.from_dict(checkpoint_data["plan"])
        return plan

    @classmethod
    def list_checkpoints(cls, checkpoint_dir: str = ".rev_checkpoints") -> List[Dict[str, Any]]:
        """List all available checkpoints.

        Args:
            checkpoint_dir: Directory containing checkpoints

        Returns:
            List of checkpoint info dicts
        """
        import os
        import json
        from datetime import datetime

        if not os.path.exists(checkpoint_dir):
            return []

        checkpoints = []
        for filename in sorted(os.listdir(checkpoint_dir), reverse=True):
            if filename.endswith(".json"):
                filepath = os.path.join(checkpoint_dir, filename)
                try:
                    with open(filepath, "r") as f:
                        data = json.load(f)

                    checkpoints.append({
                        "filename": filename,
                        "filepath": filepath,
                        "timestamp": data.get("timestamp"),
                        "tasks_total": len(data["plan"]["tasks"]),
                        "summary": data["plan"].get("summary", "")
                    })
                except:
                    pass

        return checkpoints
