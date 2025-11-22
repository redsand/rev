#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive REPL mode for iterative development with session memory."""

import sys
import re

from rev.execution import planning_mode, execution_mode
from rev.models.task import TaskStatus
from rev.config import set_escape_interrupt, get_escape_interrupt
from rev.terminal.input import get_input_with_escape
from rev.tools.registry import get_available_tools


def repl_mode():
    """Interactive REPL for iterative development with session memory."""
    print("agent.min REPL - Type /exit to quit, /help for commands")
    print("  ℹ️  Running in autonomous mode - destructive operations will prompt")
    print("  ⚡ Press ESC to immediately submit input and stop current operation")

    # Session context to maintain memory across prompts
    session_context = {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": ""
    }

    while True:
        try:
            sys.stdout.flush()  # Ensure prompt is displayed immediately
            user_input, escape_pressed = get_input_with_escape("\nagent> ")
            user_input = user_input.strip()

            # If escape was pressed, show indicator and submit immediately
            if escape_pressed:
                print("  [ESC pressed - submitting immediately]")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting REPL")
            break

        if not user_input:
            continue

        if user_input in ["/exit", "/quit", ":q"]:
            print("Exiting REPL")
            if session_context["tasks_completed"]:
                print(f"\nSession Summary:")
                print(f"  - Tasks completed: {len(session_context['tasks_completed'])}")
                print(f"  - Files reviewed: {len(session_context['files_reviewed'])}")
                print(f"  - Files modified: {len(session_context['files_modified'])}")
            break

        if user_input == "/help":
            print("""
Commands:
  /exit, /quit, :q  - Exit REPL
  /help             - Show this help
  /status           - Show session summary
  /clear            - Clear session memory

Input shortcuts:
  ESC               - Immediately submit input and stop current operation
  Ctrl+C            - Exit REPL

Otherwise, describe a task and the agent will plan and execute it.
Autonomous mode: destructive operations require confirmation, others run automatically.
            """)
            continue

        if user_input == "/status":
            print(f"\nSession Summary:")
            print(f"  - Tasks completed: {len(session_context['tasks_completed'])}")
            print(f"  - Files reviewed: {len(session_context['files_reviewed'])}")
            print(f"  - Files modified: {len(session_context['files_modified'])}")
            if session_context["last_summary"]:
                print(f"\nLast execution:")
                print(f"  {session_context['last_summary']}")
            continue

        if user_input == "/clear":
            session_context = {
                "tasks_completed": [],
                "files_modified": set(),
                "files_reviewed": set(),
                "last_summary": ""
            }
            print("Session memory cleared")
            continue

        # Execute task with auto-approve (no initial prompt, scary ops still prompt)
        # Reset interrupt flag before execution
        set_escape_interrupt(False)

        plan = planning_mode(user_input)
        tools = get_available_tools()
        success = execution_mode(plan, auto_approve=True, tools=tools)

        # Reset interrupt flag after execution (in case it was set)
        set_escape_interrupt(False)

        # Update session context
        for task in plan.tasks:
            if task.status == TaskStatus.COMPLETED:
                session_context["tasks_completed"].append(task.description)
                # Track files for context
                if task.action_type in ["review", "read"]:
                    # Extract file names from task description
                    files = re.findall(r'[\w\-./]+\.\w+', task.description)
                    session_context["files_reviewed"].update(files)
                elif task.action_type in ["edit", "add", "write"]:
                    files = re.findall(r'[\w\-./]+\.\w+', task.description)
                    session_context["files_modified"].update(files)

        session_context["last_summary"] = plan.get_summary()
