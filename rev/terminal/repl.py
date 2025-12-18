#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive REPL mode for iterative development with session memory."""

import sys
import re
import os

from rev.execution import planning_mode, execution_mode, streaming_execution_mode
from rev.execution.orchestrator import run_orchestrated
from rev.models.task import TaskStatus
from rev import config
from rev.config import EscapeInterrupt, set_escape_interrupt
from rev.terminal.input import get_input_with_escape, get_history
from rev.terminal.commands import execute_command
from rev.terminal.formatting import colorize, Colors, Symbols, get_color_status
from rev.terminal.escape_monitor import escape_monitor_context
from rev.tools.registry import get_available_tools
from rev.settings_manager import get_default_mode, apply_saved_settings
from rev.llm.client import get_token_usage


def repl_mode(force_tui: bool = False):
    """Interactive REPL for iterative development with session memory.

    The REPL is intended for interactive use. When standard input is not a TTY
    (e.g., in CI pipelines), ``sys.stdin.isatty()`` returns ``False``.
    In such non‑interactive environments the REPL would block waiting for
    input, causing automated runs to hang. Detect this early and exit
    gracefully with a short message.
    """
    use_tui = force_tui or os.getenv("REV_TUI", "").lower() in {"1", "true", "yes", "on"}
    # Exit early in non-interactive environments
    if not sys.stdin.isatty() and not use_tui:
        print("[rev] Non-interactive environment detected - exiting REPL.")
        return

    # Print welcome message with styling
    if use_tui:
        try:
            from rev.terminal.tui import TUI
            tui = TUI(prompt=f"{colorize('rev', Colors.BRIGHT_MAGENTA)}{colorize('>', Colors.BRIGHT_BLACK)} ")
            def _tui_log(msg: str):
                tui.log(msg)
            def _tui_print(msg: str):
                tui.log(msg)
            printer = _tui_print
            logger = _tui_log
        except Exception as e:
            print(f"[rev] TUI unavailable ({e}); falling back to standard REPL.")
            use_tui = False

    if not use_tui:
        print(f"{colorize('rev Interactive REPL', Colors.BRIGHT_CYAN, bold=True)}")
        print(f"{colorize('-' * 80, Colors.BRIGHT_BLACK)}")
        print(f"  {colorize('[i] Type /help for commands', Colors.BRIGHT_BLUE)}")
        print(f"  {colorize('[i] Running in autonomous mode - destructive operations will prompt', Colors.BRIGHT_YELLOW)}")
        print(f"  {colorize(f'[!] Press ESC to submit input immediately', Colors.BRIGHT_GREEN)}")
        printer = print
        logger = print

    # Show color status if disabled
    if not Colors.is_enabled() and not use_tui:
        print(f"  [!]  {get_color_status()}")

    default_mode_name, default_mode_config = get_default_mode()

    # Session context to maintain memory across prompts
    session_context = {
        "tasks_completed": [],
        "files_modified": set(),
        "files_reviewed": set(),
        "last_summary": "",
        "last_result": None,
        "token_usage": {"total": 0, "prompt": 0, "completion": 0},
        "execution_mode": default_mode_name,
        "mode_config": default_mode_config,
        "additional_dirs": [],
    }

    # Apply saved settings if they exist
    apply_saved_settings(session_context)

    def _handle_input_line(user_input: str):
        nonlocal session_context
        user_input = user_input.strip()
        if not user_input:
            return
        if user_input.startswith('/'):
            parts = user_input[1:].split()
            if not parts:
                return
            cmd_name = parts[0]
            cmd_args = parts[1:]
            get_history().add_command(user_input)
            result = execute_command(cmd_name, cmd_args, session_context)
            if result == "__EXIT__":
                logger(f"\n{colorize('Exiting REPL', Colors.BRIGHT_CYAN)}")
                if session_context["tasks_completed"]:
                    logger(f"\n{colorize('Session Summary:', Colors.BRIGHT_WHITE, bold=True)}")
                    logger(f"  {Symbols.BULLET} Tasks completed: {len(session_context['tasks_completed'])}")
                    logger(f"  {Symbols.BULLET} Files reviewed: {len(session_context['files_reviewed'])}")
                    logger(f"  {Symbols.BULLET} Files modified: {len(session_context['files_modified'])}")
                raise SystemExit
            if result:
                logger(result)
            return

        get_history().add_input(user_input)
        set_escape_interrupt(False)
        mode_cfg = session_context.get("mode_config", {})
        try:
            with escape_monitor_context(check_interval=0.05):
                if mode_cfg.get("orchestrate", False):
                    session_context["last_result"] = run_orchestrated(
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
                    plan = (
                        session_context["last_result"].plan
                        if hasattr(session_context["last_result"], "plan")
                        and session_context["last_result"].plan
                        else None
                    )
                else:
                    plan = planning_mode(
                        user_input,
                        max_plan_tasks=config.MAX_PLAN_TASKS,
                        max_planning_iterations=config.MAX_PLANNING_TOOL_ITERATIONS,
                    )
                    tools = get_available_tools()
                    session_context["last_result"] = streaming_execution_mode(
                        plan, auto_approve=True, tools=tools
                    )
        except EscapeInterrupt:
            logger(f"\n  {colorize('[ESC pressed - execution cancelled]', Colors.BRIGHT_YELLOW)}")
            plan = None
        finally:
            set_escape_interrupt(False)

        if session_context.get("last_result") is not None:
            logger(session_context["last_result"])

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

    if use_tui:
        tui.log(f"{colorize('rev TUI', Colors.BRIGHT_CYAN, bold=True)}")
        tui.log(f"{colorize('-' * 80, Colors.BRIGHT_BLACK)}")
        tui.log(f"{colorize('[i] Type /help for commands', Colors.BRIGHT_BLUE)}")
        tui.log(f"{colorize('[i] Running in autonomous mode - destructive operations will prompt', Colors.BRIGHT_YELLOW)}")
        tui.log(f"{colorize(f'[!] Press ESC to submit input immediately', Colors.BRIGHT_GREEN)}")
        try:
            tui.run(_handle_input_line)
        except SystemExit:
            pass
        except Exception as e:
            tui.log(f"[TUI ERROR] {e}")
    else:
        while True:
            try:
                prompt = f"\n{colorize('rev', Colors.BRIGHT_MAGENTA)}{colorize('>', Colors.BRIGHT_BLACK)} "
                sys.stdout.flush()
                user_input, escape_pressed = get_input_with_escape(prompt)
                user_input = user_input.strip()
                if escape_pressed:
                    print(f"  {colorize('[ESC pressed - input cleared]', Colors.BRIGHT_YELLOW)}")
            except (KeyboardInterrupt, EOFError):
                print("\nExiting REPL")
                break

            try:
                _handle_input_line(user_input)
            except SystemExit:
                break
