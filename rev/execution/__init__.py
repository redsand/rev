"""
Execution module for planning and executing CI/CD tasks.

This package contains the execution phase functionality including:
- Planning mode: Generates comprehensive task execution plans
- Execution mode: Executes tasks sequentially or concurrently
- Safety checks: Validates and confirms potentially destructive operations
"""

from rev.execution.planner import planning_mode, PLANNING_SYSTEM
from rev.execution.executor import (
    execution_mode,
    execute_single_task,
    concurrent_execution_mode,
    EXECUTION_SYSTEM
)
from rev.execution.safety import (
    is_scary_operation,
    prompt_scary_operation,
    clear_prompt_decisions,
    SCARY_OPERATIONS,
    format_operation_description,
)

__all__ = [
    # Planner
    "planning_mode",
    "PLANNING_SYSTEM",
    # Executor
    "execution_mode",
    "execute_single_task",
    "concurrent_execution_mode",
    "EXECUTION_SYSTEM",
    # Safety
    "is_scary_operation",
    "prompt_scary_operation",
    "clear_prompt_decisions",
    "format_operation_description",
    "SCARY_OPERATIONS",
]
