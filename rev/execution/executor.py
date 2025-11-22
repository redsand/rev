"""
Execution mode implementations for sequential and concurrent task execution.

This module provides the execution phase functionality that runs planned tasks
with support for sequential and concurrent execution modes, including tool
invocation and error handling.

Performance optimizations:
- Message history management to prevent unbounded growth (60-80% token reduction)
- Sliding window keeps recent context while summarizing old messages
"""

import json
import sys
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev.tools.registry import execute_tool
from rev.llm.client import ollama_chat
from rev.config import get_system_info_cached, get_escape_interrupt, set_escape_interrupt
from rev.execution.safety import is_scary_operation, prompt_scary_operation
from rev.execution.reviewer import review_action, display_action_review, format_review_feedback_for_llm
from rev.execution.session import SessionTracker, create_message_summary_from_history

EXECUTION_SYSTEM = """You are an autonomous CI/CD agent executing tasks.

IMPORTANT - System Context:
You will be provided with OS information. Use this to:
- Choose correct shell commands (bash for Linux/Mac, PowerShell/cmd for Windows)
- Select platform-specific tools and file paths
- Use appropriate path separators (/ for Unix, \\ for Windows)
- Adapt commands to the target environment

You have these tools available:
- read_file: Read file contents
- write_file: Create or modify files
- list_dir: List files matching pattern
- search_code: Search code with regex
- git_diff: View current changes
- apply_patch: Apply unified diff patches
- run_cmd: Execute shell commands (use shell-appropriate syntax)
- run_tests: Run test suite
- get_repo_context: Get repo status
- get_system_info: Get OS, version, architecture, and shell type

Work methodically:
1. Understand the current task
2. Gather necessary information (read files, search code)
3. Make changes (edit, add, or delete files)
4. Validate changes (run tests)
5. Report completion

Use unified diffs (apply_patch) for editing files. Always preserve formatting.
After making changes, run tests to ensure nothing broke.

Be concise. Execute the task and report success or failure."""


def _summarize_old_messages(messages: List[Dict], tracker: 'SessionTracker' = None) -> str:
    """Summarize completed tasks from old messages.

    Args:
        messages: List of old message dicts to summarize
        tracker: Optional SessionTracker for enhanced summary

    Returns:
        Concise summary string of completed work
    """
    # Use enhanced summary if tracker available
    if tracker:
        return create_message_summary_from_history(messages, tracker)

    # Fallback: basic message-based summarization
    tasks_completed = []
    tools_used = []

    for msg in messages:
        # Extract task descriptions from user messages
        if msg.get("role") == "user" and "Task:" in msg.get("content", ""):
            content = msg["content"]
            if "Task:" in content:
                task_line = content.split("Task:", 1)[1].split("\n")[0].strip()
                if task_line and task_line not in tasks_completed:
                    tasks_completed.append(task_line)

        # Extract tool usage from tool messages
        if msg.get("role") == "tool":
            tool_name = msg.get("name", "unknown")
            if tool_name not in tools_used:
                tools_used.append(tool_name)

    # Build concise summary
    summary_parts = []
    if tasks_completed:
        # Limit to first 10 tasks
        task_list = tasks_completed[:10]
        summary_parts.append(f"Completed {len(tasks_completed)} tasks:")
        summary_parts.extend([f"  • {t[:80]}" for t in task_list])
        if len(tasks_completed) > 10:
            summary_parts.append(f"  ... and {len(tasks_completed) - 10} more")

    if tools_used:
        summary_parts.append(f"\nTools used: {', '.join(tools_used[:15])}")

    return "\n".join(summary_parts) if summary_parts else "Previous work completed successfully."


def _manage_message_history(messages: List[Dict], max_recent: int = 20, tracker: 'SessionTracker' = None) -> List[Dict]:
    """Keep recent messages and summarize old ones to prevent unbounded growth.

    This optimization prevents token explosion in long-running sessions by:
    1. Keeping the system message
    2. Summarizing old messages (tasks completed, tools used)
    3. Keeping the most recent N messages for context

    Args:
        messages: Current message history
        max_recent: Number of recent messages to keep (default: 20)
        tracker: Optional SessionTracker for enhanced summaries

    Returns:
        Trimmed message list with summary of old messages
    """
    if len(messages) <= max_recent + 1:  # +1 for system message
        return messages

    # Separate system message, old messages, and recent messages
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    start_idx = 1 if system_msg else 0

    # Keep last max_recent messages as-is
    recent_messages = messages[-max_recent:]

    # Messages to summarize (everything except system and recent)
    old_messages = messages[start_idx:-max_recent]

    if len(old_messages) > 0:
        # Create summary of completed work (use tracker if available)
        summary = _summarize_old_messages(old_messages, tracker)
        summary_msg = {
            "role": "user",
            "content": f"[Summary of previous work]\n{summary}\n\n[Continuing with recent context...]"
        }

        # Rebuild: system + summary + recent messages
        if system_msg:
            return [system_msg, summary_msg] + recent_messages
        else:
            return [summary_msg] + recent_messages

    return messages


def execution_mode(plan: ExecutionPlan, approved: bool = False, auto_approve: bool = True, tools: list = None, enable_action_review: bool = False) -> bool:
    """Execute all tasks in the plan iteratively.

    This function executes tasks sequentially, maintaining a conversation with
    the LLM for context and handling tool invocations. It supports safety checks
    for destructive operations.

    Args:
        plan: ExecutionPlan with tasks to execute
        approved: Legacy parameter (ignored, kept for compatibility)
        auto_approve: If True (default), runs autonomously without initial approval.
                      Scary operations still require confirmation regardless.
        tools: List of available tools for LLM function calling (optional)
        enable_action_review: If True, review each action before execution (default: False)

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("EXECUTION MODE")
    print("=" * 60)

    # No upfront approval needed - runs autonomously
    # Scary operations will still prompt individually
    if not auto_approve:
        print("\nThis will execute all tasks with full autonomy.")
        print("⚠️  Note: Destructive operations will still require confirmation.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting autonomous execution...\n")
    if auto_approve:
        print("  ℹ️  Running in autonomous mode. Destructive operations will prompt for confirmation.\n")

    # Get system info for context
    sys_info = get_system_info_cached()
    system_context = f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{EXECUTION_SYSTEM}"""

    messages = [{"role": "system", "content": system_context}]
    max_iterations = 10000  # Very high limit to effectively remove restriction
    iteration = 0

    # Initialize session tracker for comprehensive summarization
    session_tracker = SessionTracker()
    print(f"  📊 Session tracking enabled (ID: {session_tracker.session_id})\n")

    while not plan.is_complete() and iteration < max_iterations:
        # Check for escape key interrupt
        if get_escape_interrupt():
            print("\n⚠️  Execution interrupted by ESC key")
            set_escape_interrupt(False)

            # Mark current task as stopped if it's in progress
            current_task = plan.get_current_task()
            if current_task and current_task.status == TaskStatus.IN_PROGRESS:
                plan.mark_task_stopped(current_task)

            # Save checkpoint for resume
            try:
                checkpoint_path = plan.save_checkpoint()
                print(f"✓ Checkpoint saved to: {checkpoint_path}")
                print(f"  Use 'rev resume {checkpoint_path}' to continue")
            except Exception as e:
                print(f"✗ Failed to save checkpoint: {e}")

            return False

        iteration += 1
        current_task = plan.get_current_task()

        print(f"\n[Task {plan.current_index + 1}/{len(plan.tasks)}] {current_task.description}")
        print(f"[Type: {current_task.action_type}]")

        current_task.status = TaskStatus.IN_PROGRESS

        # Track task start
        session_tracker.track_task_started(current_task.description)

        # Add task to conversation
        messages.append({
            "role": "user",
            "content": f"""Task: {current_task.description}
Action type: {current_task.action_type}

Execute this task completely. When done, respond with TASK_COMPLETE."""
        })

        # Execute task with tool calls
        task_iterations = 0
        max_task_iterations = 10000  # Very high limit to effectively remove restriction
        task_complete = False

        while task_iterations < max_task_iterations and not task_complete:
            # Check for escape key interrupt during task execution
            if get_escape_interrupt():
                print("\n⚠️  Task execution interrupted by ESC key")
                set_escape_interrupt(False)

                # Mark current task as stopped
                plan.mark_task_stopped(current_task)

                # Save checkpoint for resume
                try:
                    checkpoint_path = plan.save_checkpoint()
                    print(f"✓ Checkpoint saved to: {checkpoint_path}")
                    print(f"  Use 'rev resume {checkpoint_path}' to continue")
                except Exception as e:
                    print(f"✗ Failed to save checkpoint: {e}")

                return False

            task_iterations += 1

            # Try with tools, fall back to no-tools if needed
            response = ollama_chat(messages, tools=tools)

            if "error" in response:
                error_msg = response['error']
                print(f"  ✗ Error: {error_msg}")

                # If we keep getting errors, try without tools
                if "400" in error_msg and task_iterations < 3:
                    print(f"  → Retrying without tool support...")
                    response = ollama_chat(messages, tools=None)

                if "error" in response:
                    plan.mark_failed(error_msg)
                    break

            msg = response.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            # Add assistant response to conversation
            messages.append(msg)

            # Execute tool calls FIRST before checking completion
            if tool_calls:
                for tool_call in tool_calls:
                    # Check for escape key interrupt before each tool execution
                    if get_escape_interrupt():
                        print("\n⚠️  Tool execution interrupted by ESC key")
                        set_escape_interrupt(False)

                        # Mark current task as stopped
                        plan.mark_task_stopped(current_task)

                        # Save checkpoint for resume
                        try:
                            checkpoint_path = plan.save_checkpoint()
                            print(f"✓ Checkpoint saved to: {checkpoint_path}")
                            print(f"  Use 'rev resume {checkpoint_path}' to continue")
                        except Exception as e:
                            print(f"✗ Failed to save checkpoint: {e}")

                        task_complete = True
                        break

                    func = tool_call.get("function", {})
                    tool_name = func.get("name")
                    tool_args = func.get("arguments", {})

                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            tool_args = {}

                    # Check if this is a scary operation
                    is_scary, scary_reason = is_scary_operation(
                        tool_name,
                        tool_args,
                        current_task.action_type
                    )

                    if is_scary:
                        operation_desc = f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(tool_args.items())[:3])})"
                        if not prompt_scary_operation(operation_desc, scary_reason):
                            print(f"  ✗ Operation cancelled by user")
                            plan.mark_failed("User cancelled destructive operation")
                            task_complete = True
                            break

                    # Action review (if enabled)
                    action_review = None
                    if enable_action_review:
                        action_desc = f"{tool_name} with {len(tool_args)} arguments"
                        action_review = review_action(
                            action_type=current_task.action_type,
                            action_description=action_desc,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            context=current_task.description
                        )

                        if not action_review.approved:
                            display_action_review(action_review, action_desc)
                            print(f"  ✗ Action blocked by review agent")

                            # Inject feedback into conversation so LLM can adjust
                            feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                            if feedback:
                                messages.append({
                                    "role": "user",
                                    "content": feedback
                                })

                            # Don't fail immediately - let LLM try a different approach
                            continue
                        elif action_review.security_warnings or action_review.concerns:
                            display_action_review(action_review, action_desc)

                    result = execute_tool(tool_name, tool_args)

                    # Track tool usage
                    session_tracker.track_tool_call(tool_name, tool_args)

                    # Inject review feedback into conversation (if any concerns/warnings)
                    if enable_action_review and action_review:
                        feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                        if feedback:
                            messages.append({
                                "role": "user",
                                "content": feedback
                            })

                    # Add tool result to conversation
                    messages.append({
                        "role": "tool",
                        "content": result
                    })

                    # Check for test failures and track results
                    if tool_name == "run_tests":
                        session_tracker.track_test_results(result)
                        try:
                            result_data = json.loads(result)
                            if result_data.get("rc", 0) != 0:
                                print(f"  ⚠ Tests failed (rc={result_data['rc']})")
                        except:
                            pass

            # Check if task is complete AFTER executing tool calls
            if "TASK_COMPLETE" in content or "task complete" in content.lower():
                print(f"  ✓ Task completed")
                plan.mark_completed(content)
                session_tracker.track_task_completed(current_task.description)
                task_complete = True
                break

            # If model responds but doesn't use tools and doesn't complete task
            if not tool_calls and content:
                # Model is thinking/responding without tool calls
                print(f"  → {content[:200]}")

                # If model keeps responding without tools or completion, it might not support them
                if task_iterations >= 3:
                    error_msg = "Model does not support tool calling. Consider using a model with tool support."
                    print(f"  ⚠ Model not using tools. Marking task as needs manual intervention.")
                    plan.mark_failed(error_msg)
                    session_tracker.track_task_failed(current_task.description, error_msg)
                    break

        if not task_complete and task_iterations >= max_task_iterations:
            error_msg = "Exceeded iteration limit"
            print(f"  ✗ Task exceeded iteration limit")
            plan.mark_failed(error_msg)
            session_tracker.track_task_failed(current_task.description, error_msg)

        # OPTIMIZATION: Manage message history to prevent unbounded growth
        # Trim every 10 messages or when it exceeds 30 messages
        if len(messages) > 30:
            messages_before = len(messages)
            messages = _manage_message_history(messages, max_recent=20, tracker=session_tracker)
            messages_trimmed = messages_before - len(messages)
            if messages_trimmed > 0:
                print(f"  ℹ️  Message history optimized: {messages_before} → {len(messages)} messages")

    # Final summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())
    print()

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○",
            TaskStatus.STOPPED: "⏸"
        }.get(task.status, "?")

        print(f"{status_icon} {i}. {task.description} [{task.status.value}]")
        if task.error:
            print(f"    Error: {task.error}")

    print("=" * 60)

    # Finalize and display session summary
    session_tracker.finalize()
    print("\n" + "=" * 60)
    print("SESSION SUMMARY")
    print("=" * 60)
    print(session_tracker.get_summary(detailed=False))
    print("=" * 60)

    # Save session summary to disk
    try:
        summary_path = session_tracker.save_to_file()
        print(f"\n📊 Session summary saved to: {summary_path}")
    except Exception as e:
        print(f"\n⚠️  Failed to save session summary: {e}")

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)


def execute_single_task(task: Task, plan: ExecutionPlan, sys_info: Dict[str, Any], auto_approve: bool = True, tools: list = None, enable_action_review: bool = False) -> bool:
    """Execute a single task (for concurrent execution).

    This function is designed to be run in a thread pool and executes a single
    task independently with proper tool invocation and error handling.

    Args:
        task: The task to execute
        plan: The ExecutionPlan containing all tasks
        sys_info: System information for context
        auto_approve: If True, skip initial approval prompt
        tools: List of available tools for LLM function calling (optional)
        enable_action_review: If True, review each action before execution (default: False)

    Returns:
        True if task completed successfully, False otherwise
    """
    print(f"\n[Task {task.task_id + 1}/{len(plan.tasks)}] {task.description}")
    print(f"[Type: {task.action_type}]")

    plan.mark_task_in_progress(task)

    system_context = f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{EXECUTION_SYSTEM}"""

    messages = [{"role": "system", "content": system_context}]

    # Add task to conversation
    messages.append({
        "role": "user",
        "content": f"""Task: {task.description}
Action type: {task.action_type}

Execute this task completely. When done, respond with TASK_COMPLETE."""
    })

    # Execute task with tool calls
    task_iterations = 0
    max_task_iterations = 10000
    task_complete = False

    while task_iterations < max_task_iterations and not task_complete:
        task_iterations += 1

        # Try with tools, fall back to no-tools if needed
        response = ollama_chat(messages, tools=tools)

        if "error" in response:
            error_msg = response['error']
            print(f"  ✗ Error: {error_msg}")

            # If we keep getting errors, try without tools
            if "400" in error_msg and task_iterations < 3:
                print(f"  → Retrying without tool support...")
                response = ollama_chat(messages, tools=None)

            if "error" in response:
                plan.mark_task_failed(task, error_msg)
                return False

        msg = response.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # Add assistant response to conversation
        messages.append(msg)

        # Execute tool calls FIRST before checking completion
        if tool_calls:
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name")
                tool_args = func.get("arguments", {})

                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}

                # Check if this is a scary operation
                is_scary, scary_reason = is_scary_operation(
                    tool_name,
                    tool_args,
                    task.action_type
                )

                if is_scary:
                    operation_desc = f"{tool_name}({', '.join(f'{k}={v!r}' for k, v in list(tool_args.items())[:3])})"
                    if not prompt_scary_operation(operation_desc, scary_reason):
                        print(f"  ✗ Operation cancelled by user")
                        plan.mark_task_failed(task, "User cancelled destructive operation")
                        return False

                # Action review (if enabled)
                action_review = None
                if enable_action_review:
                    action_desc = f"{tool_name} with {len(tool_args)} arguments"
                    action_review = review_action(
                        action_type=task.action_type,
                        action_description=action_desc,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        context=task.description
                    )

                    if not action_review.approved:
                        display_action_review(action_review, action_desc)
                        print(f"  ✗ Action blocked by review agent")

                        # Inject feedback into conversation so LLM can adjust
                        feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                        if feedback:
                            messages.append({
                                "role": "user",
                                "content": feedback
                            })

                        # Don't fail immediately - let LLM try a different approach
                        continue
                    elif action_review.security_warnings or action_review.concerns:
                        display_action_review(action_review, action_desc)

                result = execute_tool(tool_name, tool_args)

                # Inject review feedback into conversation (if any concerns/warnings)
                if enable_action_review and action_review:
                    feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                    if feedback:
                        messages.append({
                            "role": "user",
                            "content": feedback
                        })

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "content": result
                })

                # Check for test failures
                if tool_name == "run_tests":
                    try:
                        result_data = json.loads(result)
                        if result_data.get("rc", 0) != 0:
                            print(f"  ⚠ Tests failed (rc={result_data['rc']})")
                    except:
                        pass

        # Check if task is complete AFTER executing tool calls
        if "TASK_COMPLETE" in content or "task complete" in content.lower():
            print(f"  ✓ Task completed")
            plan.mark_task_completed(task, content)
            return True

        # If model responds but doesn't use tools and doesn't complete task
        if not tool_calls and content:
            # Model is thinking/responding without tool calls
            print(f"  → {content[:200]}")

            # If model keeps responding without tools or completion, it might not support them
            if task_iterations >= 3:
                print(f"  ⚠ Model not using tools. Marking task as needs manual intervention.")
                plan.mark_task_failed(task, "Model does not support tool calling. Consider using a model with tool support.")
                return False

    if not task_complete:
        print(f"  ✗ Task exceeded iteration limit")
        plan.mark_task_failed(task, "Exceeded iteration limit")
        return False

    return True


def concurrent_execution_mode(plan: ExecutionPlan, max_workers: int = 2, auto_approve: bool = True, tools: list = None, enable_action_review: bool = False) -> bool:
    """Execute tasks in the plan concurrently with dependency tracking.

    This function executes tasks in parallel while respecting task dependencies.
    It uses a ThreadPoolExecutor to manage concurrent task execution and ensures
    only tasks with satisfied dependencies are executed.

    Args:
        plan: ExecutionPlan with tasks to execute
        max_workers: Maximum number of concurrent tasks (default: 2)
        auto_approve: If True (default), runs autonomously without initial approval
        tools: List of available tools for LLM function calling (optional)
        enable_action_review: If True, review each action before execution (default: False)

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("CONCURRENT EXECUTION MODE")
    print("=" * 60)
    print(f"  ℹ️  Max concurrent tasks: {max_workers}")

    if not auto_approve:
        print("\nThis will execute tasks in parallel with full autonomy.")
        print("⚠️  Note: Destructive operations will still require confirmation.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting concurrent autonomous execution...\n")
    if auto_approve:
        print("  ℹ️  Running in autonomous mode. Destructive operations will prompt for confirmation.\n")

    # Get system info for context
    sys_info = get_system_info_cached()

    # Use ThreadPoolExecutor for concurrent execution
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        while plan.has_pending_tasks():
            # Get tasks that are ready to execute (dependencies met)
            available_slots = max_workers - len(futures)
            if available_slots > 0:
                executable_tasks = plan.get_executable_tasks(max_count=available_slots)

                # Submit new tasks
                for task in executable_tasks:
                    future = executor.submit(execute_single_task, task, plan, sys_info, auto_approve, tools, enable_action_review)
                    futures[future] = task

            # Wait for at least one task to complete
            if futures:
                done, _ = as_completed(futures.keys()), None
                for future in list(done):
                    task = futures.pop(future)
                    try:
                        success = future.result()
                        if not success:
                            print(f"  ⚠ Task {task.task_id + 1} failed: {task.error}")
                    except Exception as e:
                        print(f"  ✗ Task {task.task_id + 1} crashed: {e}")
                        plan.mark_task_failed(task, str(e))
                    break  # Process one completion at a time
            else:
                # No tasks running and no tasks ready - check if we're stuck
                if plan.has_pending_tasks():
                    print("  ⚠ Warning: Tasks have unmet dependencies. Possible deadlock.")
                    break

    # Final summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())
    print()

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○",
            TaskStatus.STOPPED: "⏸"
        }.get(task.status, "?")

        deps_str = f" (depends on: {task.dependencies})" if task.dependencies else ""
        print(f"{status_icon} {i}. {task.description} [{task.status.value}]{deps_str}")
        if task.error:
            print(f"    Error: {task.error}")

    print("=" * 60)

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)


def fix_validation_failures(
    validation_feedback: str,
    user_request: str,
    tools: list = None,
    enable_action_review: bool = False,
    max_fix_attempts: int = 5
) -> bool:
    """Attempt to fix validation failures based on feedback.

    This creates a self-healing mechanism where the LLM sees validation failures
    and attempts to fix them automatically.

    Args:
        validation_feedback: Formatted validation feedback from validator
        user_request: Original user request for context
        tools: List of available tools for LLM function calling
        enable_action_review: Whether to review fix actions
        max_fix_attempts: Maximum number of fix attempts

    Returns:
        True if fixes were attempted successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("AUTO-FIX MODE - Addressing Validation Failures")
    print("=" * 60)

    # Get system info for context
    sys_info = get_system_info_cached()
    system_context = f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{EXECUTION_SYSTEM}

IMPORTANT: You are in AUTO-FIX mode. Your task is to analyze validation failures
and create fixes for them. Be methodical and targeted - fix one issue at a time."""

    messages = [
        {"role": "system", "content": system_context},
        {"role": "user", "content": f"""Original task: {user_request}

{validation_feedback}

Please analyze these validation failures and fix them. Complete each fix and report TASK_COMPLETE when all issues are resolved."""}
    ]

    iteration = 0
    fixes_complete = False

    while iteration < max_fix_attempts and not fixes_complete:
        iteration += 1
        print(f"\n→ Fix attempt {iteration}/{max_fix_attempts}")

        # Get LLM response
        response = ollama_chat(messages, tools=tools)

        if "error" in response:
            print(f"  ✗ Error during fix: {response['error']}")
            return False

        msg = response.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # Add assistant response to conversation
        messages.append(msg)

        # Execute tool calls
        if tool_calls:
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name")
                tool_args = func.get("arguments", {})

                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}

                print(f"  → {tool_name}...")

                # Action review if enabled
                if enable_action_review:
                    from rev.execution.reviewer import review_action, display_action_review, format_review_feedback_for_llm
                    action_desc = f"{tool_name} with {len(tool_args)} arguments"
                    action_review = review_action(
                        action_type="fix",
                        action_description=action_desc,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        context="Auto-fixing validation failures"
                    )

                    if not action_review.approved:
                        display_action_review(action_review, action_desc)
                        feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                        if feedback:
                            messages.append({"role": "user", "content": feedback})
                        continue

                # Execute the fix
                result = execute_tool(tool_name, tool_args)

                # Add result to conversation
                messages.append({
                    "role": "tool",
                    "content": result
                })

        # Check if fixes are complete
        if "TASK_COMPLETE" in content or "task complete" in content.lower():
            print(f"  ✓ Fixes completed")
            fixes_complete = True
            break

        # If no tool calls and no completion, provide guidance
        if not tool_calls:
            print(f"  → LLM response: {content[:200]}")

    if iteration >= max_fix_attempts:
        print(f"  ⚠️  Reached maximum fix attempts ({max_fix_attempts})")
        return False

    return fixes_complete
