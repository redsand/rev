#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive REPL mode for iterative development with session memory."""

import sys
import re

from rev.execution import planning_mode, execution_mode
from rev.execution.orchestrator import run_orchestrated
from rev.models.task import TaskStatus
from rev import config
from rev.config import set_escape_interrupt
from rev.terminal.input import get_input_with_escape, get_history
from rev.terminal.commands import execute_command
from rev.terminal.formatting import colorize, Colors, Symbols, get_color_status
from rev.terminal.escape_monitor import escape_monitor_context
from rev.tools.registry import get_available_tools
from rev.settings_manager import get_default_mode, apply_saved_settings
from rev.llm.client import get_token_usage


def repl_mode():
    """Interactive REPL for iterative development with session memory.

    The REPL is intended for interactive use. When standard input is not a TTY
    (e.g., in CI pipelines), ``sys.stdin.isatty()`` returns ``False``.
    In such non‑interactive environments the REPL would block waiting for
    input, causing automated runs to hang. Detect this early and exit
    gracefully with a short message.
    """
    # Exit early in non-interactive environments
    if not sys.stdin.isatty():
        print("[rev] Non-interactive environment detected - exiting REPL.")
        return

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

    default_mode_name, default_mode_config = get_default_mode()

    # Session context to maintain memory across prompts
    session_context = {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": "",
        "token_usage": {"total": 0, "prompt": 0, "completion": 0},
        "execution_mode": default_mode_name,
        "mode_config": default_mode_config,
        "additional_dirs": [],
    }

    # Apply saved settings if they exist
    apply_saved_settings(session_context)

    while True:
        try:
            sys.stdout.flush()
            prompt = f"\n{colorize('rev', Colors.BRIGHT_MAGENTA)}{colorize('>', Colors.BRIGHT_BLACK)} "
            user_input, escape_pressed = get_input_with_escape(prompt)
            user_input = user_input.strip()
            if escape_pressed:
                print(f"  {colorize('[ESC pressed - submitting immediately]', Colors.BRIGHT_YELLOW)}")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting REPL")
            break

        if not user_input:
            continue

        if user_input.startswith('/'):
            parts = user_input[1:].split()
            if not parts:
                continue
            cmd_name = parts[0]
            cmd_args = parts[1:]
            get_history().add_command(user_input)
            result = execute_command(cmd_name, cmd_args, session_context)
            if result == "__EXIT__":
                print(f"\n{colorize('Exiting REPL', Colors.BRIGHT_CYAN)}")
                if session_context["tasks_completed"]:
                    print(f"\n{colorize('Session Summary:', Colors.BRIGHT_WHITE, bold=True)}")
                    print(f"  {Symbols.BULLET} Tasks completed: {len(session_context['tasks_completed'])}")
                    print(f"  {Symbols.BULLET} Files reviewed: {len(session_context['files_reviewed'])}")
                    print(f"  {Symbols.BULLET} Files modified: {len(session_context['files_modified'])}")
                break
            if result:
                print(result)
            continue

        get_history().add_input(user_input)
        set_escape_interrupt(False)
        mode_cfg = session_context.get("mode_config", {})
        with escape_monitor_context(check_interval=0.05):
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
                    parallel_workers=mode_cfg.get("parallel", 1),
                    auto_approve=True,
                    research_depth=mode_cfg.get("research_depth", "medium"),
                )
                plan = result.plan if hasattr(result, "plan") and result.plan else None
            else:
                plan = planning_mode(user_input)
                tools = get_available_tools()
                execution_mode(plan, auto_approve=True, tools=tools)
        set_escape_interrupt(False)
        if plan:
            for task in plan.tasks:
                if task.status == TaskStatus.COMPLETED:
                    session_context["tasks_completed"].append(task.description)
                    if task.action_type in ["review", "read"]:
                        files = re.findall(r'[\w\-./]+\.\w+', task.description)
                        session_context["files_reviewed"].update(files)
                    elif task.action_type in ["edit", "add", "write"]:
                        files = re.findall(r'[\w\-./]+\.\w+', task.description)
                        session_context["files_modified"].update(files)
            session_context["last_summary"] = plan.get_summary()
            session_context["token_usage"] = get_token_usage()
