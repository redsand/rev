"""
GoalTracker - Tracks goals and maps changes to goals for traceability.

This module provides functionality to:
- Define and track goals (user intentions, desired outcomes)
- Map tasks and changes to goals
- Provide traceability from completed work back to original goals
- Track goal progress and completion status
- Support hierarchical goals (parent/child relationships)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Any
from enum import Enum

from rev.models.task import Task, TaskStatus


class GoalStatus(Enum):
    """Status of a goal."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class GoalPriority(Enum):
    """Priority level for goals."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class GoalChange:
    """Represents a change associated with a goal.

    Attributes:
        change_id: Unique identifier for this change
        goal_id: ID of the goal this change is associated with
        task: The task that created this change
        file_path: Path to the file that was changed (if applicable)
        change_type: Type of change (e.g., "create", "modify", "delete")
        description: Description of what was changed
        timestamp: When the change was made
        old_content: Previous content (for modifications)
        new_content: New content (for modifications)
    """

    change_id: str
    goal_id: str
    task: Optional[Task] = None
    file_path: Optional[str] = None
    change_type: str = ""
    description: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    old_content: Optional[str] = None
    new_content: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "change_id": self.change_id,
            "goal_id": self.goal_id,
            "task_id": self.task.task_id if self.task else None,
            "file_path": self.file_path,
            "change_type": self.change_type,
            "description": self.description,
            "timestamp": self.timestamp.isoformat(),
            "old_content": self.old_content,
            "new_content": self.new_content,
        }


@dataclass
class Goal:
    """Represents a goal in the execution trace.

    Attributes:
        goal_id: Unique identifier for this goal
        description: Human-readable description of the goal
        status: Current status of the goal
        priority: Priority level of the goal
        parent_goal_id: ID of the parent goal (if this is a sub-goal)
        child_goal_ids: List of child goal IDs
        created_at: When this goal was created
        updated_at: When this goal was last updated
        completed_at: When this goal was completed
        changes: List of changes associated with this goal
        metadata: Additional metadata about the goal
    """

    goal_id: str
    description: str
    status: GoalStatus = GoalStatus.NOT_STARTED
    priority: GoalPriority = GoalPriority.MEDIUM
    parent_goal_id: Optional[str] = None
    child_goal_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    changes: List[GoalChange] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_change(self, change: GoalChange) -> None:
        """Add a change to this goal."""
        self.changes.append(change)
        self.updated_at = datetime.now()

    def mark_started(self) -> None:
        """Mark this goal as in progress."""
        self.status = GoalStatus.IN_PROGRESS
        self.updated_at = datetime.now()

    def mark_completed(self) -> None:
        """Mark this goal as completed."""
        self.status = GoalStatus.COMPLETED
        self.completed_at = datetime.now()
        self.updated_at = datetime.now()

    def mark_failed(self) -> None:
        """Mark this goal as failed."""
        self.status = GoalStatus.FAILED
        self.updated_at = datetime.now()

    def mark_blocked(self) -> None:
        """Mark this goal as blocked."""
        self.status = GoalStatus.BLOCKED
        self.updated_at = datetime.now()

    def add_child_goal(self, child_goal_id: str) -> None:
        """Add a child goal."""
        if child_goal_id not in self.child_goal_ids:
            self.child_goal_ids.append(child_goal_id)
            self.updated_at = datetime.now()

    def get_progress(self) -> float:
        """Get progress of this goal (0.0 to 1.0).

        For a goal with child goals, progress is calculated as the average
        progress of all child goals. For a leaf goal (no children),
        progress is based on status:
        - NOT_STARTED: 0.0
        - IN_PROGRESS: 0.5
        - COMPLETED: 1.0
        - FAILED: 0.0
        - BLOCKED: 0.0
        - CANCELLED: 0.0

        Returns:
            Progress as a float between 0.0 and 1.0
        """
        if not self.child_goal_ids:
            # Leaf goal - use status-based progress
            if self.status == GoalStatus.COMPLETED:
                return 1.0
            elif self.status == GoalStatus.IN_PROGRESS:
                return 0.5
            else:
                return 0.0
        else:
            # Has children - needs GoalTracker to calculate progress
            # This will be set by GoalTracker
            return getattr(self, "_calculated_progress", 0.0)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "parent_goal_id": self.parent_goal_id,
            "child_goal_ids": self.child_goal_ids,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "changes": [c.to_dict() for c in self.changes],
            "metadata": self.metadata,
            "progress": self.get_progress(),
        }


class GoalTracker:
    """Tracks goals and maps changes to goals for traceability.

    This class manages the lifecycle of goals and provides methods to:
    - Create, update, and query goals
    - Map tasks and changes to goals
    - Track progress towards goals
    - Generate traceability reports
    """

    def __init__(self):
        """Initialize GoalTracker."""
        self._goals: Dict[str, Goal] = {}
        self._goal_counter = 0

    def create_goal(
        self,
        description: str,
        parent_goal_id: Optional[str] = None,
        priority: GoalPriority = GoalPriority.MEDIUM,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Goal:
        """Create a new goal.

        Args:
            description: Human-readable description of the goal
            parent_goal_id: Optional ID of the parent goal
            priority: Priority level of the goal
            metadata: Additional metadata about the goal

        Returns:
            The newly created Goal
        """
        self._goal_counter += 1
        goal_id = f"goal_{self._goal_counter}"

        goal = Goal(
            goal_id=goal_id,
            description=description,
            priority=priority,
            parent_goal_id=parent_goal_id,
            metadata=metadata or {}
        )

        self._goals[goal_id] = goal

        # Add this goal as a child of the parent goal
        if parent_goal_id and parent_goal_id in self._goals:
            self._goals[parent_goal_id].add_child_goal(goal_id)

        return goal

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        """Get a goal by ID.

        Args:
            goal_id: The ID of the goal to retrieve

        Returns:
            The Goal if found, None otherwise
        """
        return self._goals.get(goal_id)

    def get_all_goals(self) -> List[Goal]:
        """Get all goals.

        Returns:
            List of all goals
        """
        return list(self._goals.values())

    def get_root_goals(self) -> List[Goal]:
        """Get all root goals (goals without parents).

        Returns:
            List of root goals
        """
        return [goal for goal in self._goals.values() if goal.parent_goal_id is None]

    def get_child_goals(self, parent_goal_id: str) -> List[Goal]:
        """Get all child goals of a parent goal.

        Args:
            parent_goal_id: The ID of the parent goal

        Returns:
            List of child goals
        """
        return [
            self._goals[goal_id]
            for goal_id in self._goals.get(parent_goal_id, Goal("", "")).child_goal_ids
            if goal_id in self._goals
        ]

    def update_goal_status(self, goal_id: str, status: GoalStatus) -> None:
        """Update the status of a goal.

        Args:
            goal_id: The ID of the goal to update
            status: The new status
        """
        if goal_id in self._goals:
            self._goals[goal_id].status = status
            self._goals[goal_id].updated_at = datetime.now()

            if status == GoalStatus.COMPLETED:
                self._goals[goal_id].completed_at = datetime.now()

    def map_task_to_goal(self, task: Task, goal_id: str, change_type: str = "task",
                        description: Optional[str] = None, file_path: Optional[str] = None) -> GoalChange:
        """Map a task to a goal, creating a change record.

        Args:
            task: The task to map
            goal_id: The ID of the goal
            change_type: Type of change (e.g., "create", "modify", "delete", "task")
            description: Optional description of the change
            file_path: Optional path to the file that was changed

        Returns:
            The created GoalChange
        """
        change_id = f"change_{goal_id}_{task.task_id}_{datetime.now().timestamp()}"

        change = GoalChange(
            change_id=change_id,
            goal_id=goal_id,
            task=task,
            file_path=file_path,
            change_type=change_type,
            description=description or task.description,
        )

        if goal_id in self._goals:
            self._goals[goal_id].add_change(change)

            # If goal was not started, mark it as in progress
            if self._goals[goal_id].status == GoalStatus.NOT_STARTED:
                self._goals[goal_id].mark_started()

        return change

    def get_changes_for_goal(self, goal_id: str) -> List[GoalChange]:
        """Get all changes associated with a goal.

        Args:
            goal_id: The ID of the goal

        Returns:
            List of changes for the goal
        """
        goal = self._goals.get(goal_id)
        return goal.changes if goal else []

    def get_goal_progress(self, goal_id: str) -> float:
        """Calculate the progress of a goal.

        Args:
            goal_id: The ID of the goal

        Returns:
            Progress as a float between 0.0 and 1.0
        """
        goal = self._goals.get(goal_id)
        if not goal:
            return 0.0

        if not goal.child_goal_ids:
            # Leaf goal - use status-based progress
            return goal.get_progress()
        else:
            # Parent goal - average progress of children
            child_goals = self.get_child_goals(goal_id)
            if not child_goals:
                return goal.get_progress()

            child_progress = sum(self.get_goal_progress(child.goal_id) for child in child_goals)
            progress = child_progress / len(child_goals)
            goal._calculated_progress = progress
            return progress

    def get_goals_by_status(self, status: GoalStatus) -> List[Goal]:
        """Get all goals with a specific status.

        Args:
            status: The status to filter by

        Returns:
            List of goals with the specified status
        """
        return [goal for goal in self._goals.values() if goal.status == status]

    def get_goals_by_priority(self, priority: GoalPriority) -> List[Goal]:
        """Get all goals with a specific priority.

        Args:
            priority: The priority to filter by

        Returns:
            List of goals with the specified priority
        """
        return [goal for goal in self._goals.values() if goal.priority == priority]

    def generate_traceability_report(self, goal_id: str) -> Dict[str, Any]:
        """Generate a traceability report for a goal.

        Args:
            goal_id: The ID of the goal

        Returns:
            Dictionary containing traceability information
        """
        goal = self._goals.get(goal_id)
        if not goal:
            return {"error": f"Goal {goal_id} not found"}

        report = {
            "goal": goal.to_dict(),
            "changes": [c.to_dict() for c in goal.changes],
            "child_goals": [],
            "progress": self.get_goal_progress(goal_id),
        }

        for child_goal_id in goal.child_goal_ids:
            child_report = self.generate_traceability_report(child_goal_id)
            if "error" not in child_report:
                report["child_goals"].append(child_report)

        return report

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all goals.

        Returns:
            Dictionary containing summary statistics
        """
        total_goals = len(self._goals)
        completed = len(self.get_goals_by_status(GoalStatus.COMPLETED))
        in_progress = len(self.get_goals_by_status(GoalStatus.IN_PROGRESS))
        not_started = len(self.get_goals_by_status(GoalStatus.NOT_STARTED))
        failed = len(self.get_goals_by_status(GoalStatus.FAILED))
        blocked = len(self.get_goals_by_status(GoalStatus.BLOCKED))
        cancelled = len(self.get_goals_by_status(GoalStatus.CANCELLED))

        total_changes = sum(len(goal.changes) for goal in self._goals.values())

        return {
            "total_goals": total_goals,
            "completed": completed,
            "in_progress": in_progress,
            "not_started": not_started,
            "failed": failed,
            "blocked": blocked,
            "cancelled": cancelled,
            "total_changes": total_changes,
            "completion_rate": completed / total_goals if total_goals > 0 else 0.0,
        }