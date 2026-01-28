"""
TaskRunner - Handles task execution and sub-agent dispatching.

This module is responsible for:
- Dispatching tasks to appropriate sub-agents
- Managing the task execution loop
- Handling task lifecycle (start, complete, fail)
"""

import re
import traceback
from pathlib import Path
from typing import Optional, Dict, Any

from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext
from rev.execution.action_normalizer import normalize_action_type
from rev.agents.subagent_io import build_subagent_output


class TaskRunner:
    """Handles task execution and sub-agent dispatching."""

    def __init__(self, orchestrator):
        """Initialize TaskRunner with reference to orchestrator.

        Args:
            orchestrator: The Orchestrator instance for accessing shared state
        """
        self.orchestrator = orchestrator

    def dispatch_task(self, context: RevContext, task: Optional[Task] = None) -> bool:
        """Dispatch a task to the appropriate sub-agent.

        Args:
            context: The RevContext for this session
            task: The task to dispatch, or None to use the next task from the plan

        Returns:
            True if task was dispatched and completed successfully, False otherwise
        """
        if task is None:
            if not context.plan or not context.plan.tasks:
                return False
            task = context.plan.tasks[0]

        if task.status == TaskStatus.COMPLETED:
            return True

        # Apply read-only constraints
        task = self._apply_read_only_constraints(task)

        # Guardrail: if the planner accidentally schedules a file creation as a directory creation
        # (common in decomposed tasks like "create __init__.py"), coerce to `add` so we can use write_file.
        if (task.action_type or "").lower() == "create_directory" and re.search(r"\.py\b", task.description, re.IGNORECASE):
            task.action_type = "add"

        # Normalize action types (aliases + fuzzy typos) before registry lookup.
        task.action_type = normalize_action_type(
            task.action_type,
            fallback=task.description,
            logger=self.orchestrator.debug_logger
        )

        # Check if the action is allowed (e.g., write operations in read-only mode)
        if not self._is_action_allowed(context, task):
            self._handle_restricted_action(task, context)
            return False

        # Execute the task
        return self._execute_task(context, task)

    def _apply_read_only_constraints(self, task: Task) -> Task:
        """Apply read-only mode constraints to the task.

        Args:
            task: The task to apply constraints to

        Returns:
            The modified task
        """
        # Delegated to orchestrator for now
        return self.orchestrator._apply_read_only_constraints(task)

    def _is_action_allowed(self, context: RevContext, task: Task) -> bool:
        """Check if the task action is allowed.

        Args:
            context: The RevContext
            task: The task to check

        Returns:
            True if the action is allowed
        """
        # Check if write operations are allowed
        from rev.execution.tool_constraints import has_write_tool, WRITE_ACTIONS

        if task.action_type in WRITE_ACTIONS:
            if has_write_tool(task):
                if context.config.read_only:
                    # Write operation in read-only mode
                    return False
        return True

    def _handle_restricted_action(self, task: Task, context: RevContext):
        """Handle a restricted action (e.g., write in read-only mode).

        Args:
            task: The restricted task
            context: The RevContext
        """
        print(f"  [SKIPPED] Action '{task.action_type}' not allowed in read-only mode")
        task.status = TaskStatus.STOPPED
        task.error = f"Action not allowed in read-only mode"

    def _execute_task(self, context: RevContext, task: Task) -> bool:
        """Execute a task by dispatching to the appropriate sub-agent.

        Args:
            context: The RevContext
            task: The task to execute

        Returns:
            True if task completed successfully, False otherwise
        """
        try:
            # Mark task as in progress
            context.plan.mark_task_in_progress(task)

            # Dispatch to appropriate sub-agent based on action type
            result = self._dispatch_to_agent(context, task)

            # Update task status based on result
            if result:
                task.status = TaskStatus.COMPLETED
                context.plan.mark_task_completed(task)
                return True
            else:
                task.status = TaskStatus.FAILED
                return False

        except Exception as e:
            task.status = TaskStatus.FAILED
            tb = traceback.format_exc()
            task.error = f"{e}\n{tb}"
            context.add_error(f"Task execution exception for task {task.task_id}: {e}\n{tb}")
            return False

    def _dispatch_to_agent(self, context: RevContext, task: Task) -> bool:
        """Dispatch task to the appropriate sub-agent.

        This method is responsible for routing tasks to the correct
        sub-agent (code_writing, refactor, testing, debug, etc.) based
        on the task's action_type and description.

        Args:
            context: The RevContext
            task: The task to dispatch

        Returns:
            True if task completed successfully, False otherwise
        """
        # For now, delegate back to orchestrator's existing implementation
        # This will be fully migrated in subsequent steps
        return self.orchestrator._dispatch_to_sub_agents(context, task)