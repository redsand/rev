#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive REPL mode for iterative development with session memory."""

import sys
import re

from rev.execution import planning_mode, execution_mode
from rev.execution.orchestrator import run_orchestrated
from rev.models.task import TaskStatus
from rev import config
from rev.config import set_escape_interrupt, get_escape_interrupt
from rev.terminal.input import get_input_with_escape
from rev.terminal.commands import execute_command
from rev.terminal.formatting import colorize, Colors, Symbols, get_color_status
from rev.terminal.escape_monitor import escape_monitor_context
from rev.tools.registry import get_available_tools


def repl_mode():
    """Interactive REPL for iterative development with session memory."""
    # Print welcome message with styling
    print(f"\n{colorize('rev Interactive REPL', Colors.BRIGHT_CYAN, bold=True)}")
    print(f"{colorize('-' * 80, Colors.BRIGHT_BLACK)}")
    print(f"  {colorize('[i] Type /help for commands', Colors.BRIGHT_BLUE)}")
    print(f"  {colorize('[i] Running in autonomous mode - destructive operations will prompt', Colors.BRIGHT_YELLOW)}")
    print(f"  {colorize(f'[!] Press ESC to submit input immediately', Colors.BRIGHT_GREEN)}")

    # Show color status if disabled
    if not Colors.is_enabled():
        print(f"  [!]  {get_color_status()}")

    print()

    # Session context to maintain memory across prompts
    session_context = {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": "",
        "token_usage": {
            "total": 0,
            "prompt": 0,
            "completion": 0
        },
        "execution_mode": "standard",  # Default mode
        "mode_config": {  # Default standard mode with orchestration
            "orchestrate": True,
            "research": True,
            "learn": False,
            "review": True,
            "review_strictness": "moderate",
            "research_depth": "medium",
            "validate": True,
            "auto_fix": False,
            "action_review": False,
            "parallel": 2
        }
    }

    while True:
        try:
            sys.stdout.flush()  # Ensure prompt is displayed immediately
            # Create styled prompt
            prompt = f"\n{colorize('rev', Colors.BRIGHT_MAGENTA)}{colorize('>', Colors.BRIGHT_BLACK)} "
            user_input, escape_pressed = get_input_with_escape(prompt)
            user_input = user_input.strip()

            # If escape was pressed, show indicator and submit immediately
            if escape_pressed:
                print(f"  {colorize('[ESC pressed - submitting immediately]', Colors.BRIGHT_YELLOW)}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting REPL")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            # Parse command and arguments
            parts = user_input[1:].split()
            if not parts:
                continue

            cmd_name = parts[0]
            cmd_args = parts[1:]

            # Execute command
            result = execute_command(cmd_name, cmd_args, session_context)

            # Check for exit marker
            if result == "__EXIT__":
                print(f"\n{colorize('Exiting REPL', Colors.BRIGHT_CYAN)}")
                if session_context["tasks_completed"]:
                    print(f"\n{colorize('Session Summary:', Colors.BRIGHT_WHITE, bold=True)}")
                    print(f"  {Symbols.BULLET} Tasks completed: {len(session_context['tasks_completed'])}")
                    print(f"  {Symbols.BULLET} Files reviewed: {len(session_context['files_reviewed'])}")
                    print(f"  {Symbols.BULLET} Files modified: {len(session_context['files_modified'])}")
                break

            # Display command result
            if result:
                print(result)
            continue

        # Execute task with auto-approve (no initial prompt, scary ops still prompt)
        # Reset interrupt flag before execution
        set_escape_interrupt(False)

        # Get mode configuration
        mode_cfg = session_context.get("mode_config", {})

        # Use escape monitor for responsive ESC key handling during execution
        with escape_monitor_context(check_interval=0.05):  # Check every 50ms
            # Use orchestrator if enabled in mode config
            if mode_cfg.get("orchestrate", False):
                result = run_orchestrated(
                    user_input,
                    config.ROOT,
                    enable_learning=mode_cfg.get("learn", False),
                    enable_research=mode_cfg.get("research", True),
                    enable_review=mode_cfg.get("review", True),
                    enable_validation=mode_cfg.get("validate", True),
                    review_strictness=mode_cfg.get("review_strictness", "moderate"),
                    enable_action_review=mode_cfg.get("action_review", False),
                    enable_auto_fix=mode_cfg.get("auto_fix", False),
                    parallel_workers=mode_cfg.get("parallel", 2),
                    auto_approve=True,  # REPL is always auto-approve (scary ops still prompt)
                    research_depth=mode_cfg.get("research_depth", "medium")
                )
                success = result.success
                # Extract plan from result for session tracking
                plan = result.plan if hasattr(result, 'plan') and result.plan else None
            else:
                # Use simple planning + execution mode
                plan = planning_mode(user_input)
                tools = get_available_tools()
                success = execution_mode(plan, auto_approve=True, tools=tools)

        # Reset interrupt flag after execution (in case it was set)
        set_escape_interrupt(False)

        # Update session context
        if plan:
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
