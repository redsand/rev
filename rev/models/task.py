#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Task and plan models for rev."""

import re
import threading
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from rev import config


_EXPLICIT_VERB_PATTERN = re.compile(r"\b(run|rerun|re-run|execute|verify|validate|check)\b", re.IGNORECASE)
_TEST_KEYWORD_PATTERN = re.compile(
    r"\b(tests?|test suite|pytest|jest|vitest|mocha|unittest|unit tests?|integration tests?|e2e tests?)\b",
    re.IGNORECASE,
)
_LINT_KEYWORD_PATTERN = re.compile(
    r"\b(lint|linting|linter|eslint|ruff|pylint|mypy|type ?check|tsc|clippy|go vet|golangci-lint)\b",
    re.IGNORECASE,
)


def explicitly_requests_tests(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if _EXPLICIT_VERB_PATTERN.search(lowered) and _TEST_KEYWORD_PATTERN.search(lowered):
        return True
    stripped = lowered.strip()
    for prefix in ("test ", "tests ", "pytest", "jest", "vitest", "mocha", "npm test", "pnpm test", "yarn test"):
        if stripped.startswith(prefix):
            return True
    return False


def explicitly_requests_lint(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if _EXPLICIT_VERB_PATTERN.search(lowered) and _LINT_KEYWORD_PATTERN.search(lowered):
        return True
    stripped = lowered.strip()
    for prefix in ("lint ", "linting ", "eslint", "ruff", "pylint", "mypy", "typecheck", "type check", "tsc"):
        if stripped.startswith(prefix):
            return True
    return False


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class TaskStateTransition:
    """Represents a single state transition in task lifecycle."""
    from_state: TaskStatus
    to_state: TaskStatus
    timestamp: datetime = field(default_factory=datetime.now)
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class InvalidTransitionError(Exception):
    """Raised when an invalid task state transition is attempted."""

    def __init__(self, from_state: TaskStatus, to_state: TaskStatus, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}. {reason}")


class TaskStateMachine:
    """State machine for validating and tracking task state transitions.

    This class enforces valid state transitions for tasks and maintains a
    history of all transitions for debugging and audit purposes.

    Valid Transitions:
    - PENDING -> IN_PROGRESS (start task)
    - PENDING -> STOPPED (skip task)
    - IN_PROGRESS -> COMPLETED (task succeeded)
    - IN_PROGRESS -> FAILED (task failed)
    - IN_PROGRESS -> STOPPED (abort task)
    - FAILED -> IN_PROGRESS (retry task)
    - STOPPED -> PENDING (replan/resume task)
    - COMPLETED -> (terminal, no outgoing transitions)
    """

    # Valid transitions: from_state -> list of allowed to_states
    VALID_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
        TaskStatus.PENDING: [TaskStatus.IN_PROGRESS, TaskStatus.STOPPED],
        TaskStatus.IN_PROGRESS: [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.STOPPED],
        TaskStatus.FAILED: [TaskStatus.IN_PROGRESS],
        TaskStatus.STOPPED: [TaskStatus.PENDING],
        TaskStatus.COMPLETED: [],  # Terminal state
    }

    # Terminal states (no valid outgoing transitions)
    TERMINAL_STATES: frozenset = frozenset([TaskStatus.COMPLETED])

    # Recoverable states (can transition back to IN_PROGRESS)
    RECOVERABLE_STATES: frozenset = frozenset([TaskStatus.FAILED, TaskStatus.STOPPED])

    def __init__(self, initial_state: TaskStatus = TaskStatus.PENDING):
        """Initialize the state machine.

        Args:
            initial_state: Starting state (default: PENDING)
        """
        self.current_state = initial_state
        self.transition_history: List[TaskStateTransition] = []

        # Record initial state
        self._record_transition(None, initial_state, "Initial state")

    def can_transition(self, to_state: TaskStatus) -> bool:
        """Check if a transition to the given state is valid.

        Args:
            to_state: The target state to check

        Returns:
            True if the transition is valid, False otherwise
        """
        return to_state in self.VALID_TRANSITIONS.get(self.current_state, [])

    def transition(self, to_state: TaskStatus, reason: str = "", **kwargs) -> TaskStateTransition:
        """Transition to a new state.

        Args:
            to_state: The target state
            reason: Optional reason for the transition
            **kwargs: Optional metadata to attach to the transition

        Returns:
            The created TaskStateTransition

        Raises:
            InvalidTransitionError: If the transition is not valid
        """
        if not self.can_transition(to_state):
            valid_targets = self.VALID_TRANSITIONS.get(self.current_state, [])
            raise InvalidTransitionError(
                self.current_state,
                to_state,
                f"Valid transitions from {self.current_state.value} are: {[s.value for s in valid_targets]}"
            )

        # Extract metadata from kwargs - if metadata is passed as a keyword argument,
        # use it directly; otherwise use all kwargs as metadata
        metadata_dict = kwargs.get("metadata", {}) if "metadata" in kwargs else kwargs

        # Record and perform transition
        transition = self._record_transition(self.current_state, to_state, reason, metadata_dict or {})
        self.current_state = to_state

        return transition

    def _record_transition(
        self,
        from_state: Optional[TaskStatus],
        to_state: TaskStatus,
        reason: str = "",
        metadata: Dict[str, Any] = None
    ) -> TaskStateTransition:
        """Record a state transition in the history."""
        transition = TaskStateTransition(
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            metadata=metadata or {}
        )
        self.transition_history.append(transition)
        return transition

    def get_transition_history(self) -> List[TaskStateTransition]:
        """Get the full transition history."""
        return self.transition_history.copy()

    def get_state_duration(self, state: TaskStatus) -> Optional[float]:
        """Get the total duration spent in a given state.

        Args:
            state: The state to check

        Returns:
            Total seconds spent in the state, or None if never in that state
        """
        total_seconds = 0.0
        in_state_since = None

        for transition in self.transition_history:
            if transition.to_state == state:
                in_state_since = transition.timestamp
            elif transition.from_state == state and in_state_since is not None:
                total_seconds += (transition.timestamp - in_state_since).total_seconds()
                in_state_since = None

        # Handle case where we're still in the state
        if in_state_since is not None and self.current_state == state:
            total_seconds += (datetime.now() - in_state_since).total_seconds()

        return total_seconds if total_seconds > 0 else None

    def is_terminal(self) -> bool:
        """Check if current state is terminal (no outgoing transitions)."""
        return self.current_state in self.TERMINAL_STATES

    def is_recoverable(self) -> bool:
        """Check if the current state can recover to IN_PROGRESS."""
        return self.current_state in self.RECOVERABLE_STATES

    def get_valid_transitions(self) -> List[TaskStatus]:
        """Get list of valid transitions from current state."""
        return self.VALID_TRANSITIONS.get(self.current_state, []).copy()

    @classmethod
    def validate_transition(cls, from_state: TaskStatus, to_state: TaskStatus) -> bool:
        """Check if a transition between two states is valid (static method).

        This is useful for validation without creating a state machine instance.

        Args:
            from_state: The source state
            to_state: The target state

        Returns:
            True if the transition is valid
        """
        return to_state in cls.VALID_TRANSITIONS.get(from_state, [])

    def to_dict(self) -> Dict[str, Any]:
        """Convert state machine to dict for serialization."""
        return {
            "current_state": self.current_state.value,
            "is_terminal": self.is_terminal(),
            "is_recoverable": self.is_recoverable(),
            "transition_count": len(self.transition_history),
            "transitions": [
                {
                    "from": t.from_state.value if t.from_state else None,
                    "to": t.to_state.value,
                    "timestamp": t.timestamp.isoformat(),
                    "reason": t.reason,
                    "metadata": t.metadata,
                }
                for t in self.transition_history
            ]
        }


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
        self._state_machine = TaskStateMachine(TaskStatus.PENDING)
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
        self.tool_events: List[Dict[str, Any]] = []  # Recorded tool executions

    @property
    def status(self) -> TaskStatus:
        """Get the current task status."""
        return self._state_machine.current_state

    @status.setter
    def status(self, new_status: TaskStatus):
        """Set the task status with state machine validation.

        Note: For backwards compatibility, this allows setting status directly.
        Consider using set_status() instead for better error handling.
        """
        try:
            self._state_machine.transition(new_status, reason="Direct status assignment")
        except InvalidTransitionError:
            # For backwards compatibility, log but don't raise
            # In production, this should be a warning or error
            self._state_machine.current_state = new_status
            self._state_machine._record_transition(
                self._state_machine.current_state,
                new_status,
                reason="Forced transition (invalid)"
            )

    def set_status(self, new_status: TaskStatus, reason: str = "", **metadata) -> None:
        """Set the task status with validation and metadata.

        Args:
            new_status: The new status
            reason: Reason for the status change
            **metadata: Additional metadata about the transition

        Raises:
            InvalidTransitionError: If the transition is not valid
        """
        self._state_machine.transition(new_status, reason=reason, **metadata)

    def get_state_history(self) -> List[TaskStateTransition]:
        """Get the full state transition history for this task."""
        return self._state_machine.get_transition_history()

    def can_transition_to(self, status: TaskStatus) -> bool:
        """Check if the task can transition to the given status."""
        return self._state_machine.can_transition(status)

    def is_terminal(self) -> bool:
        """Check if the task is in a terminal state."""
        return self._state_machine.is_terminal()

    def is_recoverable(self) -> bool:
        """Check if the task can be recovered (retried)."""
        return self._state_machine.is_recoverable()

    def get_valid_next_states(self) -> List[TaskStatus]:
        """Get list of valid next states for this task."""
        return self._state_machine.get_valid_transitions()

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
            "priority": self.priority,
            "tool_events": self.tool_events,
            "state_machine": self._state_machine.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        """Create a Task from a dictionary."""
        task = cls(
            description=data["description"],
            action_type=data.get("action_type", "general"),
            dependencies=data.get("dependencies", [])
        )
        status_raw = str(data.get("status", "pending"))
        # Accept both plain values and enum-like strings (e.g., "TaskStatus.COMPLETED")
        status_value = status_raw.split(".")[-1]
        try:
            target_status = TaskStatus(status_value)
            # Use state machine to set status properly
            task.set_status(target_status, reason="Restored from checkpoint")
        except Exception:
            # Keep default PENDING status
            pass
        except InvalidTransitionError:
            # For restoration from checkpoint, force the state
            task._state_machine.current_state = target_status
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
        task.tool_events = data.get("tool_events", [])
        return task


class ExecutionPlan:
    """Manages the task checklist for iterative execution with dependency tracking."""
    def __init__(self, tasks: Optional[List[Task]] = None):
        self.tasks: List[Task] = tasks or []
        self.current_index = 0
        self.lock = threading.Lock()  # Thread-safe operations
        self.goals: List = []  # List of Goal objects for goal-oriented execution
        # Ensure task IDs are correctly numbered if tasks are provided upon instantiation
        for i, task in enumerate(self.tasks):
            task.task_id = i

    def add_task(self, description: str, action_type: str = "general", dependencies: List[int] = None):
        task = Task(description, action_type, dependencies)
        task.task_id = len(self.tasks)
        self.tasks.append(task)
        return task

    def insert_subtasks_after(self, parent_task: Task, subtasks: List[Dict[str, Any]]) -> List[Task]:
        """Insert subtasks immediately after a parent task in the execution plan.

        This enables dynamic task expansion during execution. Subtasks are inserted
        right after the parent task and inherit dependencies from the parent.

        Args:
            parent_task: The task after which to insert subtasks
            subtasks: List of dicts with 'description', 'action_type', optional 'complexity'

        Returns:
            List of created Task objects
        """
        if not subtasks:
            return []

        with self.lock:
            parent_idx = parent_task.task_id
            if parent_idx is None or parent_idx < 0 or parent_idx >= len(self.tasks):
                raise ValueError(f"Invalid parent task ID: {parent_idx}")

            created_tasks = []
            insert_position = parent_idx + 1

            for i, subtask_data in enumerate(subtasks):
                new_task = Task(
                    description=subtask_data.get("description", "Subtask"),
                    action_type=subtask_data.get("action_type", parent_task.action_type),
                    dependencies=[parent_idx]  # Subtask depends on parent completion
                )
                new_task.complexity = subtask_data.get("complexity", "low")
                new_task.task_id = insert_position + i  # Will be renumbered below
                created_tasks.append(new_task)

            # Insert the new tasks
            for i, task in enumerate(created_tasks):
                self.tasks.insert(insert_position + i, task)

            # Renumber all tasks after insertion
            for idx, task in enumerate(self.tasks):
                old_id = task.task_id
                task.task_id = idx

                # Update dependencies that reference shifted tasks
                if old_id != idx and old_id > parent_idx:
                    # Update parent's subtasks list if needed
                    pass

            # Update parent's subtasks list
            parent_task.subtasks = [t.task_id for t in created_tasks]

            # Update dependencies in all tasks to account for renumbering
            shift_amount = len(created_tasks)
            for task in self.tasks:
                if task in created_tasks:
                    continue
                new_deps = []
                for dep_id in task.dependencies:
                    if dep_id > parent_idx:
                        # Dependency was shifted, update it
                        new_deps.append(dep_id + shift_amount)
                    else:
                        new_deps.append(dep_id)
                task.dependencies = new_deps

            return created_tasks

    def add_subtasks_to_pending(self, subtasks: List[Dict[str, Any]], after_task_id: int = None) -> List[Task]:
        """Add new subtasks to the plan that haven't been executed yet.

        Unlike insert_subtasks_after, this appends subtasks at the end of the plan,
        making them suitable for late-discovered work.

        Args:
            subtasks: List of dicts with 'description', 'action_type', optional 'complexity'
            after_task_id: Optional task ID that these subtasks depend on

        Returns:
            List of created Task objects
        """
        if not subtasks:
            return []

        with self.lock:
            created_tasks = []
            dependencies = [after_task_id] if after_task_id is not None else []

            for subtask_data in subtasks:
                new_task = Task(
                    description=subtask_data.get("description", "Subtask"),
                    action_type=subtask_data.get("action_type", "general"),
                    dependencies=dependencies.copy()
                )
                new_task.complexity = subtask_data.get("complexity", "low")
                new_task.task_id = len(self.tasks)
                self.tasks.append(new_task)
                created_tasks.append(new_task)

                # If sequential execution is desired, make each subtask depend on the previous
                if subtask_data.get("sequential", False) and created_tasks:
                    dependencies = [new_task.task_id]

            return created_tasks

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

    def mark_task_in_progress(self, task: Task, reason: str = "Starting task"):
        """Mark a task as in progress."""
        with self.lock:
            task.set_status(TaskStatus.IN_PROGRESS, reason=reason)

    def mark_task_completed(self, task: Task, result: str = None, reason: str = "Task completed successfully"):
        """Mark a specific task as completed."""
        with self.lock:
            task.set_status(TaskStatus.COMPLETED, reason=reason)
            task.result = result

    def mark_task_failed(self, task: Task, error: str, reason: str = "Task failed"):
        """Mark a specific task as failed."""
        with self.lock:
            task.set_status(TaskStatus.FAILED, reason=reason, error=error)
            task.error = error

    def mark_task_stopped(self, task: Task, reason: str = "Task stopped"):
        """Mark a specific task as stopped (for resume functionality).

        Also advances current_index to prevent the execution loop from getting
        stuck retrying the same task indefinitely.
        """
        with self.lock:
            task.set_status(TaskStatus.STOPPED, reason=reason)
            # Advance to next task so sequential execution doesn't get stuck
            # on the same stopped task (similar to mark_failed behavior)
            if task.task_id is not None and task.task_id == self.current_index:
                self.current_index += 1

    def mark_completed(self, result: str = None):
        """Legacy method for sequential execution compatibility.

        Note: For backwards compatibility, allows PENDING -> COMPLETED transition
        by going through IN_PROGRESS implicitly. New code should use mark_task_in_progress
        followed by mark_task_completed.
        """
        if self.current_index < len(self.tasks):
            task = self.tasks[self.current_index]
            # For backwards compatibility, handle PENDING -> COMPLETED
            if task.status == TaskStatus.PENDING:
                task.set_status(TaskStatus.IN_PROGRESS, reason="Legacy mark_completed (implicit start)")
            task.set_status(TaskStatus.COMPLETED, reason="Legacy mark_completed")
            task.result = result
            self.current_index += 1

    def mark_failed(self, error: str):
        """Legacy method for sequential execution compatibility.

        Note: For backwards compatibility, allows PENDING -> FAILED transition
        by going through IN_PROGRESS implicitly. New code should use mark_task_in_progress
        followed by mark_task_failed.
        """
        if self.current_index < len(self.tasks):
            task = self.tasks[self.current_index]
            # For backwards compatibility, handle PENDING -> FAILED
            if task.status == TaskStatus.PENDING:
                task.set_status(TaskStatus.IN_PROGRESS, reason="Legacy mark_failed (implicit start)")
            task.set_status(TaskStatus.FAILED, reason="Legacy mark_failed", error=error)
            task.error = error
            # Advance to the next task so execution can continue instead of
            # repeatedly retrying the same failed task.
            self.current_index += 1

    def is_complete(self) -> bool:
        """Check if all tasks are done (completed, failed, or stopped)."""
        return all(
            task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.STOPPED]
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
            rollback_steps.append("  CRITICAL: Deleted files cannot be recovered without backup")
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
        explicit_tests = explicitly_requests_tests(task.description) or task.action_type == "test"
        explicit_lint = explicitly_requests_lint(task.description)
        
        from rev.tools.project_types import detect_project_type, detect_test_command
        project_type = detect_project_type(config.ROOT)
        detected_cmd = detect_test_command(config.ROOT)
        
        test_cmd = None
        if detected_cmd:
            test_cmd = " ".join(detected_cmd)
        elif project_type == "python":
            test_cmd = "pytest"
        elif project_type in ("node", "vue", "react", "nextjs"):
            test_cmd = "npm test"
        elif project_type == "go": test_cmd = "go test ./..."
        elif project_type == "rust": test_cmd = "cargo test"
        elif project_type == "csharp": test_cmd = "dotnet test"
        elif project_type == "ruby": test_cmd = "bundle exec rake test"
        elif project_type == "php": test_cmd = "vendor/bin/phpunit"
        elif project_type == "java_maven": test_cmd = "mvn test"
        elif project_type == "java_gradle" or project_type == "kotlin": test_cmd = "./gradlew test"
        elif project_type == "flutter": test_cmd = "flutter test"

        # Common validation
        steps.append("Check for syntax errors")

        if task.action_type in ["add", "edit", "refactor", "create"]:
            if explicit_lint:
                steps.append("Run linter to check code quality")
            steps.append("Verify imports and dependencies")

        if task.action_type in ["add", "edit", "refactor", "create", "delete", "rename"]:
            if explicit_tests:
                if test_cmd:
                    steps.append(f"Run test suite: {test_cmd}")
                else:
                    steps.append("Run project test suite (command not detected)")
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
        tasks_data = data.get("tasks", [])
        if isinstance(tasks_data, dict):
            tasks_data = list(tasks_data.values())
        if not isinstance(tasks_data, list):
            tasks_data = []
        plan.tasks = [Task.from_dict(t) for t in tasks_data if isinstance(t, dict)]
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

    def save_checkpoint(self, filepath: str = None, agent_state: Dict[str, Any] = None):
        """Save the current execution state to a checkpoint file.

        Args:
            filepath: Path to save checkpoint. If None, uses default location.
            agent_state: Optional agent state dict to persist (e.g., recovery_attempts)
        """
        import json
        import os
        from datetime import datetime

        if filepath is None:
            checkpoint_dir = config.CHECKPOINTS_DIR
            os.makedirs(checkpoint_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(checkpoint_dir, f"checkpoint_{timestamp}.json")

        checkpoint_data = {
            "version": "1.2",  # Bumped version for model_config support
            "timestamp": datetime.now().isoformat(),
            "plan": self.to_dict()
        }

        # Include model/provider configuration for resume compatibility
        import os
        model_config = {}
        if os.getenv("REV_LLM_PROVIDER"):
            model_config["provider"] = os.getenv("REV_LLM_PROVIDER")
        if os.getenv("OLLAMA_MODEL"):
            model_config["model"] = os.getenv("OLLAMA_MODEL")
        if os.getenv("OLLAMA_BASE_URL"):
            model_config["base_url"] = os.getenv("OLLAMA_BASE_URL")
        if os.getenv("OPENAI_MODEL"):
            model_config["model"] = os.getenv("OPENAI_MODEL")
        if os.getenv("OPENAI_API_KEY"):
            # Don't save API keys for security
            pass
        if os.getenv("ANTHROPIC_MODEL"):
            model_config["model"] = os.getenv("ANTHROPIC_MODEL")
        if model_config:
            checkpoint_data["model_config"] = model_config

        # Include agent_state if provided (for recovery_attempts persistence)
        if agent_state:
            # Only persist recovery-related state, not transient data
            persistent_keys = [
                "total_recovery_attempts",
                "recovery_attempts",
                "task_recovery_counts",
            ]
            filtered_state = {k: v for k, v in agent_state.items() if k in persistent_keys}
            if filtered_state:
                checkpoint_data["agent_state"] = filtered_state

        with open(filepath, "w") as f:
            json.dump(checkpoint_data, f, indent=2)

        return filepath

    @classmethod
    def load_checkpoint(cls, filepath: str) -> Tuple['ExecutionPlan', Dict[str, Any], Dict[str, Any]]:
        """Load an execution plan from a checkpoint file.

        Args:
            filepath: Path to the checkpoint file

        Returns:
            Tuple of (ExecutionPlan, agent_state dict, model_config dict) restored from checkpoint
        """
        import json

        with open(filepath, "r") as f:
            checkpoint_data = json.load(f)

        plan = cls.from_dict(checkpoint_data["plan"])
        agent_state = checkpoint_data.get("agent_state", {})
        model_config = checkpoint_data.get("model_config", {})
        return plan, agent_state, model_config

    @classmethod
    def list_checkpoints(cls, checkpoint_dir: str = str(config.CHECKPOINTS_DIR)) -> List[Dict[str, Any]]:
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
                except Exception:
                    pass  # Skip malformed checkpoint files

        return checkpoints
