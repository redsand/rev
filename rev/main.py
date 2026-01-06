#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry point for rev CLI."""

import sys
import os
import argparse
import shutil
from typing import Optional

from . import config
from .cache import initialize_caches
from .execution import planning_mode, execution_mode, concurrent_execution_mode
from .execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from .execution.validator import validate_execution, ValidationStatus
from .execution.orchestrator import run_orchestrated
from .terminal import repl_mode
from .settings_manager import apply_saved_settings
from .models.task import ExecutionPlan, TaskStatus
from .tools.registry import get_available_tools
from .debug_logger import DebugLogger
from .execution.state_manager import StateManager
from rev.mcp.loader import start_mcp_servers, stop_mcp_servers


def main():
    """Main entry point for the rev CLI."""
    # Apply any saved configuration overrides before parsing arguments
    apply_saved_settings()

    # Pre-parse --workspace and --allow-external-paths early so config.ROOT and
    # .rev paths are correct before init.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--workspace", type=str, default=None)
    pre_parser.add_argument("--allow-external-paths", action="store_true", default=False)
    pre_args, _unknown = pre_parser.parse_known_args()

    # Initialize workspace from CLI args and environment variable
    from pathlib import Path
    from rev.workspace import init_workspace

    allow_external = pre_args.allow_external_paths or os.getenv("REV_ALLOW_EXTERNAL_PATHS", "").lower() == "true"
    workspace_root = Path(pre_args.workspace) if pre_args.workspace else Path.cwd()
    init_workspace(root=workspace_root, allow_external=allow_external)
    config._sync_from_workspace()

    if pre_args.workspace:
        try:
            os.chdir(str(config.ROOT))
        except Exception:
            pass

    # Ensure rev data directory exists
    config.REV_DIR.mkdir(parents=True, exist_ok=True)
    # Run log is started lazily after we know we're not doing --clean/--clear
    from rev.run_log import start_run_log, write_run_log_line
    run_log_path = None

    # Initialize cache system
    cache_dir = config.CACHE_DIR
    initialize_caches(config.ROOT, cache_dir)

    parser = argparse.ArgumentParser(
        description="rev - CI/CD Agent powered by Ollama"
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Task description (one-shot mode)"
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Interactive REPL mode"
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Use curses TUI (prompt at bottom with scrollback). Can also set REV_TUI=1"
    )
    parser.add_argument(
        "--model",
        default=config.OLLAMA_MODEL,
        help=f"Ollama model (default: {config.OLLAMA_MODEL})"
    )
    parser.add_argument(
        "--llm-provider",
        default=None,
        help="LLM provider override (ollama, openai, anthropic, gemini, localai, vllm, lmstudio)"
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace root directory (sets repo root and .rev/ state location)"
    )
    parser.add_argument(
        "--allow-external-paths",
        action="store_true",
        default=False,
        help="Allow tool access to absolute paths outside the workspace (must be in allowlist via /add-dir). Can also set REV_ALLOW_EXTERNAL_PATHS=true"
    )
    parser.add_argument(
        "--trust-workspace",
        action="store_true",
        help="Skip first-run trust disclaimer for this workspace"
    )
    parser.add_argument(
        "--base-url",
        default=config.OLLAMA_BASE_URL,
        help=f"Ollama base URL (default: {config.OLLAMA_BASE_URL})"
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Automatically approve all changes"
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Prompt for approval before execution (default: auto-approve)"
    )
    parser.add_argument(
        "-j", "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of concurrent tasks to run in parallel (default: 1)"
    )
    parser.add_argument(
        "--review",
        action="store_true",
        default=True,
        help="Enable review agent to validate plans (default: enabled)"
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Disable review agent"
    )
    parser.add_argument(
        "--review-strictness",
        choices=["lenient", "moderate", "strict"],
        default="moderate",
        help="Review agent strictness level (default: moderate)"
    )
    parser.add_argument(
        "--action-review",
        action="store_true",
        help="Enable action-level review during execution (reviews each tool call)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        default=True,
        help="Enable validation agent after execution (default: enabled)"
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Disable post-execution validation"
    )
    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Enable auto-fix for minor validation issues (linting, formatting)"
    )
    parser.add_argument(
        "--orchestrate",
        action="store_true",
        default=True,
        help="Enable orchestrator mode - coordinates all agents (default: enabled)"
    )
    parser.add_argument(
        "--no-orchestrate",
        action="store_true",
        help="Disable orchestrator mode for simple execution"
    )
    parser.add_argument(
        "--execution-mode",
        choices=["linear", "sub-agent", "inline"],
        default=None,
        help="Execution mode: 'linear' (traditional sequential), 'sub-agent' (dispatch to specialized agents). 'inline' is alias for 'linear'. Default: from REV_EXECUTION_MODE env var or 'sub-agent'"
    )
    parser.add_argument(
        "--tool-mode",
        choices=["normal", "auto-accept", "plan-only"],
        default=None,
        help="Tool execution mode: normal | auto-accept (bypass permission denials) | plan-only (no tool execution)"
    )
    parser.add_argument(
        "--no-mcp",
        action="store_true",
        help="Disable MCP server startup and registration for this run"
    )
    parser.add_argument(
        "--research",
        action="store_true",
        default=True,
        help="Enable research agent for pre-planning codebase exploration (default: enabled)"
    )
    parser.add_argument(
        "--research-depth",
        choices=["shallow", "medium", "deep"],
        default="medium",
        help="Research agent depth (default: medium)"
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="Enable learning agent for project memory across sessions"
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="latest",
        metavar="CHECKPOINT",
        help="Load session context from a checkpoint (defaults to latest if no path provided). Does not auto-continue; use --resume-continue to resume the prior plan."
    )
    parser.add_argument(
        "--resume-continue",
        action="store_true",
        help="Continue the prior plan after loading a checkpoint (requires --resume)"
    )
    parser.add_argument(
        "--list-checkpoints",
        action="store_true",
        help="List all available checkpoints"
    )
    parser.add_argument(
        "--optimize-prompt",
        action="store_true",
        help="Enable prompt optimization - analyzes and suggests improvements to vague requests"
    )
    parser.add_argument(
        "--no-optimize-prompt",
        action="store_true",
        help="Disable prompt optimization"
    )
    parser.add_argument(
        "--auto-optimize",
        action="store_true",
        help="Auto-optimize prompts without asking user (implies --optimize-prompt)"
    )
    parser.add_argument(
        "--context-guard",
        action="store_true",
        default=True,
        help="Enable ContextGuard for context validation and filtering (default: enabled)"
    )
    parser.add_argument(
        "--no-context-guard",
        action="store_true",
        help="Disable ContextGuard phase"
    )
    parser.add_argument(
        "--context-guard-auto",
        action="store_true",
        help="ContextGuard auto-discovery mode instead of interactive clarification"
    )
    parser.add_argument(
        "--context-guard-threshold",
        type=float,
        default=0.3,
        help="Relevance threshold for context filtering (0.0-1.0, default: 0.3)"
    )
    parser.add_argument(
        "--preflight",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable/disable preflight path/action corrections (default: DISABLED - marked for removal due to negative value)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable detailed debug logging to file for LLM review"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean all temporary files, caches, and logs"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        dest="clean",
        help="Alias for --clean (clean all temporary files, caches, and logs)"
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Show rev version information and exit",
    )
    parser.add_argument(
        "--ide-api",
        action="store_true",
        help="Start IDE API server (HTTP/WebSocket server for IDE integration)",
    )
    parser.add_argument(
        "--ide-lsp",
        action="store_true",
        help="Start IDE LSP server (Language Server Protocol for universal IDE support)",
    )
    parser.add_argument(
        "--ide-api-host",
        default="127.0.0.1",
        help="IDE API server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--ide-api-port",
        type=int,
        default=8765,
        help="IDE API server port (default: 8765)",
    )
    parser.add_argument(
        "--ide-lsp-host",
        default="127.0.0.1",
        help="IDE LSP server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--ide-lsp-port",
        type=int,
        default=2087,
        help="IDE LSP server port (default: 2087)",
    )
    parser.add_argument(
        "--ide-lsp-stdio",
        action="store_true",
        help="Use stdio for LSP communication instead of TCP (for direct IDE integration)",
    )


    args = parser.parse_args()
    config.EXPLICIT_YES = bool(args.yes)
    # Windows: ensure ANSI output is handled correctly in classic consoles.
    try:
        if os.name == "nt":
            import colorama

            colorama.just_fix_windows_console()
    except Exception:
        pass

    use_tui_main = args.tui or os.getenv("REV_TUI", "").lower() in {"1", "true", "yes", "on"}
    buffered_logs: list[str] = []
    initial_command: Optional[str] = None
    clean_mode = bool(args.clean)
    mcp_processes: list = []

    # Start run log only if not cleaning/clearing to avoid locking the log file being deleted.
    if not clean_mode:
        try:
            run_log_path = start_run_log()
        except Exception:
            run_log_path = None

    def _log(msg: str):
        if use_tui_main:
            try:
                # In TUI startup we buffer instead of printing; still persist to run log (unless cleaning).
                if run_log_path and not clean_mode:
                    write_run_log_line(msg)
            except Exception:
                pass
        if use_tui_main:
            buffered_logs.append(msg)
        else:
            print(msg)

    # Apply --workspace (full parser) for log visibility and safety.
    if args.workspace:
        from pathlib import Path
        config.set_workspace_root(Path(args.workspace))
        try:
            os.chdir(str(config.ROOT))
        except Exception:
            pass

    # Log workspace roots for transparency (Isolate).
    _log(f"workspace_root={config.ROOT}")
    _log(f"allowed_roots={[str(p) for p in config.get_allowed_roots()]}")
    if run_log_path:
        _log(f"run_log={run_log_path}")

    # First-run trust disclaimer per workspace
    trust_marker = config.REV_DIR / "trust.ok"
    trust_env = os.getenv("REV_TRUST_ACCEPT", "").lower() in {"1", "true", "yes", "on"}
    if not trust_marker.exists():
        disclaimer = (
            "\n[TRUST NOTICE] This is the first time rev is running in this workspace.\n"
            "rev can read/write files under the workspace root and execute shell commands.\n"
            "Ensure you trust the contents of this project before proceeding."
        )
        print(disclaimer)
        if args.trust_workspace or args.yes or trust_env:
            try:
                trust_marker.parent.mkdir(parents=True, exist_ok=True)
                trust_marker.write_text("trusted", encoding="utf-8")
                print("[OK] Workspace trusted (marker created).")
            except Exception as e:
                print(f"[WARN] Could not create trust marker: {e}")
        else:
            print("Tip: rerun with --trust-workspace or set REV_TRUST_ACCEPT=1 to skip this notice in the future.")

    # Enable LLM transaction logging if debug mode is requested
    if args.debug:
        config.LLM_TRANSACTION_LOG_ENABLED = True

    # Initialize debug logging if requested
    debug_logger = DebugLogger.initialize(enabled=args.debug)
    if args.debug:
        _log(f"Debug logging enabled: {debug_logger.log_file_path}")

    # Update config globals for ollama_chat function
    config.set_model(args.model)
    config.OLLAMA_BASE_URL = args.base_url
    if args.llm_provider:
        config.LLM_PROVIDER = args.llm_provider
        # Ensure all phases follow the provider unless overridden by env
        config.EXECUTION_PROVIDER = args.llm_provider
        config.PLANNING_PROVIDER = args.llm_provider
        config.RESEARCH_PROVIDER = args.llm_provider

    # Set execution mode if provided
    if args.execution_mode:
        config.set_execution_mode(args.execution_mode)
    # Set tool mode if provided
    if args.tool_mode:
        config.set_tool_mode(args.tool_mode)
    # Resolve MCP enablement (env/config plus CLI override)
    config.MCP_ENABLED = bool(getattr(config, "MCP_ENABLED", True)) and not args.no_mcp

    # Determine prompt optimization settings
    # Priority: CLI flags > Environment variables > defaults
    enable_prompt_optimization = True  # Default
    auto_optimize_prompt = False  # Default

    # Check environment variables
    if os.getenv("REV_OPTIMIZE_PROMPT", "").lower() == "false":
        enable_prompt_optimization = False
    if os.getenv("REV_AUTO_OPTIMIZE", "").lower() == "true":
        auto_optimize_prompt = True

    # Override with CLI flags (highest priority)
    if args.no_optimize_prompt:
        enable_prompt_optimization = False
    if args.optimize_prompt:
        enable_prompt_optimization = True
    if args.auto_optimize:
        enable_prompt_optimization = True
        auto_optimize_prompt = True

    # CRITICAL: In TUI mode, must use auto-optimize to avoid blocking input() calls
    # TUI uses curses and stdin is not available for input() prompts
    use_tui = args.tui or os.getenv("REV_TUI", "").lower() == "true"
    if use_tui and enable_prompt_optimization:
        auto_optimize_prompt = True  # Force auto-optimize in TUI mode

    # Determine ContextGuard settings
    # Priority: CLI flags > Environment variables > defaults
    enable_context_guard = True  # Default
    context_guard_interactive = True  # Default

    # Check environment variables
    if os.getenv("REV_ENABLE_CONTEXT_GUARD", "").lower() == "false":
        enable_context_guard = False
    if os.getenv("REV_CONTEXT_GUARD_INTERACTIVE", "").lower() == "false":
        context_guard_interactive = False

    # Override with CLI flags (highest priority)
    if args.no_context_guard:
        enable_context_guard = False
    if args.context_guard:
        enable_context_guard = True
    if args.context_guard_auto:
        context_guard_interactive = False

    # CRITICAL: In TUI mode, disable interactive prompts for ContextGuard too
    if use_tui and enable_context_guard:
        context_guard_interactive = False  # Auto-approve in TUI mode

    context_guard_threshold = args.context_guard_threshold

    config.PREFLIGHT_ENABLED = args.preflight

    if args.version:
        from rev.versioning import build_version_output

        print(build_version_output(config.OLLAMA_MODEL, config.get_system_info_cached()))
        sys.exit(0)


    if args.clean:
        print("Cleaning temporary files, caches, and logs...")
        if config.REV_DIR.exists():
            keep_files = {"settings.json", "secrets.json"}
            for entry in config.REV_DIR.iterdir():
                # Preserve settings/secrets
                if entry.name in keep_files:
                    continue
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=False)
                    else:
                        entry.unlink()
                except Exception as e:
                    print(f"[WARN] Clean could not remove {entry}: {e}")
        print("Clean complete.")
        sys.exit(0)

    # Initialize MCP servers (default + repo config) if enabled
    if config.MCP_ENABLED:
        try:
            from rev.mcp.client import mcp_client

            # Refresh registry to reflect current toggles
            mcp_client.servers.clear()
            mcp_client._load_default_servers()
            mcp_processes = start_mcp_servers(config.ROOT, enable=True, register=True)
            server_names = ", ".join(sorted(mcp_client.servers.keys())) or "none"
            _log(f"[mcp] enabled; servers registered: {server_names}")
            if mcp_processes:
                _log(f"[mcp] started {len(mcp_processes)} local server process(es)")
            try:
                debug_logger.log("mcp", "REGISTERED", {
                    "servers": sorted(mcp_client.servers.keys()),
                    "process_count": len(mcp_processes),
                })
            except Exception:
                pass

            # Log tool availability (static + MCP)
            try:
                from rev.tools.registry import get_tool_stats
                stats = get_tool_stats()
                _log(f"[tools] total available: {stats.get('total_tools', 'n/a')}")
                debug_logger.log("tools", "STATS", stats)
            except Exception as e:  # pragma: no cover - logging only
                _log(f"[WARN] Unable to compute tool stats: {e}")
        except Exception as e:
            _log(f"[WARN] MCP initialization failed: {e}")
    else:
        _log("[mcp] disabled for this run")

    # Handle IDE server startup
    if args.ide_api:
        try:
            from .ide.api_server import RevAPIServer
            print(f"Starting Rev IDE API server on http://{args.ide_api_host}:{args.ide_api_port}")
            print("IDE Features:")
            print("  - HTTP REST API for code analysis, testing, refactoring")
            print("  - WebSocket support for real-time updates")
            print("  - Model selection and configuration")
            print("\nAPI Endpoints:")
            print(f"  - http://{args.ide_api_host}:{args.ide_api_port}/api/v1/execute")
            print(f"  - http://{args.ide_api_host}:{args.ide_api_port}/api/v1/analyze")
            print(f"  - http://{args.ide_api_host}:{args.ide_api_port}/api/v1/models")
            print(f"  - ws://{args.ide_api_host}:{args.ide_api_port}/ws (WebSocket)")
            print("\nPress Ctrl+C to stop the server")

            server = RevAPIServer(config=config)
            server.start(host=args.ide_api_host, port=args.ide_api_port)
            sys.exit(0)
        except ImportError as e:
            print(f"Error: IDE API server dependencies not installed: {e}")
            print("Install with: pip install rev-agentic")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nIDE API server stopped")
            sys.exit(0)

    if args.ide_lsp:
        try:
            from .ide.lsp_server import RevLSPServer
            if args.ide_lsp_stdio:
                print("Starting Rev IDE LSP server on stdio")
                print("LSP Features:")
                print("  - Universal IDE support (VSCode, Vim, Emacs, Sublime, etc.)")
                print("  - Code actions for analysis, testing, refactoring")
                print("  - Documentation generation")
                print("\nPress Ctrl+C to stop the server")

                server = RevLSPServer(config=config)
                server.start_io()
            else:
                print(f"Starting Rev IDE LSP server on {args.ide_lsp_host}:{args.ide_lsp_port}")
                print("LSP Features:")
                print("  - Universal IDE support (VSCode, Vim, Emacs, Sublime, etc.)")
                print("  - Code actions for analysis, testing, refactoring")
                print("  - Documentation generation")
                print("\nPress Ctrl+C to stop the server")

                server = RevLSPServer(config=config)
                server.start(host=args.ide_lsp_host, port=args.ide_lsp_port)
        except ImportError as e:
            print(f"Error: IDE LSP server dependencies not installed: {e}")
            print("Install with: pip install rev-agentic")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nIDE LSP server stopped")
            sys.exit(0)

    # Log configuration
    debug_logger.log("main", "CONFIGURATION", {
        "model": args.model,
        "base_url": args.base_url,
        "mode": "repl" if args.repl else ("orchestrate" if args.orchestrate else "standard"),
        "execution_mode": config.get_execution_mode(),
        "parallel": args.parallel,
        "review_enabled": args.review and not args.no_review,
        "validate_enabled": args.validate and not args.no_validate,
        "auto_approve": args.yes or not args.prompt,
        "research_enabled": args.research,
        "learn_enabled": args.learn,
        "action_review_enabled": args.action_review,
        "auto_fix_enabled": args.auto_fix,
        "prompt_optimization_enabled": enable_prompt_optimization,
        "auto_optimize_prompt": auto_optimize_prompt,
        "context_guard_enabled": enable_context_guard,
        "context_guard_interactive": context_guard_interactive,
        "context_guard_threshold": context_guard_threshold,
        "preflight_enabled": config.PREFLIGHT_ENABLED,
    })

    # Handle list-checkpoints command
    if args.list_checkpoints:
        print("rev - Available Checkpoints\n")
        checkpoints = ExecutionPlan.list_checkpoints()
        if not checkpoints:
            print("No checkpoints found.")
            print(f"Checkpoints are saved in .rev/checkpoints/ directory when execution is interrupted.")
        else:
            for i, cp in enumerate(checkpoints, 1):
                print(f"{i}. {cp['filename']}")
                print(f"   Timestamp: {cp['timestamp']}")
                print(f"   Tasks: {cp['tasks_total']}")
                print(f"   Status: {cp['summary']}")
                print()
        sys.exit(0)


    _log(f"rev - CI/CD Agent")
    active_model = config.EXECUTION_MODEL or config.OLLAMA_MODEL
    _log(f"Provider: {config.LLM_PROVIDER}")
    _log(f"Model: {active_model}")

    # Model capability warnings
    MODEL_WARNINGS = {
        "glm-4.7:cloud": {
            "level": "warning",
            "issues": ["may generate corrupt unified diff patches"],
            "recommendation": "Consider using claude-sonnet-4.5 or gpt-4o for better patch generation"
        },
        "glm-4": {
            "level": "warning",
            "issues": ["may generate corrupt unified diff patches"],
            "recommendation": "Consider using claude-sonnet-4.5 or gpt-4o for better patch generation"
        },
    }

    if active_model in MODEL_WARNINGS:
        warning = MODEL_WARNINGS[active_model]
        _log(f"  ⚠️  Model Compatibility Warning:")
        for issue in warning["issues"]:
            _log(f"     - {issue}")
        _log(f"     → {warning['recommendation']}")
        _log("")

    if (config.LLM_PROVIDER or "").lower() == "ollama":
        _log(f"Ollama: {config.OLLAMA_BASE_URL}")
    _log(f"Repository: {config.ROOT}")
    if args.parallel > 1:
        _log(f"Parallel execution: {args.parallel} concurrent tasks")
    if not args.prompt:
        _log("  [i] Autonomous mode: destructive operations will prompt for confirmation")
    _log("")

    state_manager: Optional[StateManager] = None
    resume_checkpoint: Optional[str] = None
    resume_context: bool = False
    resume_plan: bool = True

    try:
        # Handle resume command
        if args.resume_continue and not args.resume:
            print("? --resume-continue requires --resume")
            sys.exit(1)
        if args.resume:
            # If resume is True (flag without value) or empty string, find latest checkpoint
            checkpoint_path = args.resume
            if checkpoint_path is True or checkpoint_path == "latest" or not checkpoint_path:
                checkpoint_path = StateManager.find_latest_checkpoint()
                if not checkpoint_path:
                    print("✗ No checkpoints found.")
                    print(f"\nCheckpoints are saved in .rev/checkpoints/ directory when execution is interrupted.")
                    print("Use --list-checkpoints to see available checkpoints.")
                    sys.exit(1)
                print(f"Using latest checkpoint: {checkpoint_path}\n")

            debug_logger.log_workflow_phase("resume", {"checkpoint": checkpoint_path})
            print(f"Loading checkpoint: {checkpoint_path}\n")
            try:
                plan, restored_agent_state = ExecutionPlan.load_checkpoint(checkpoint_path)
                state_manager = StateManager(plan)
                # Store restored agent_state to be merged into context later
                if restored_agent_state:
                    state_manager.restored_agent_state = restored_agent_state
                    print(f"  Restored agent state: {list(restored_agent_state.keys())}")
                print(f"✓ Checkpoint loaded successfully")
                print(f"  {plan.get_summary()}\n")
                debug_logger.log("main", "CHECKPOINT_LOADED", {
                    "checkpoint": args.resume,
                    "task_count": len(plan.tasks),
                    "summary": plan.get_summary()
                })
                resume_checkpoint = checkpoint_path
                resume_context = True
                resume_plan = args.resume_continue

                if args.resume_continue and config.get_execution_mode() == "sub-agent":
                    def _load_last_request() -> str:
                        try:
                            from rev.execution.session import SessionTracker
                            last_session_path = config.SESSIONS_DIR / "last_session.json"
                            if last_session_path.exists():
                                tracker = SessionTracker.load_from_file(last_session_path)
                                initial = (tracker.summary.initial_request or "").strip()
                                if initial:
                                    return initial
                        except Exception:
                            pass
                        return "Resume previous session"

                    resume_request = _load_last_request()
                    result = run_orchestrated(
                        resume_request,
                        config.ROOT,
                        enable_learning=args.learn,
                        enable_research=args.research,
                        enable_review=args.review and not args.no_review,
                        enable_validation=args.validate and not args.no_validate,
                        review_strictness=args.review_strictness,
                        enable_action_review=args.action_review,
                        enable_auto_fix=args.auto_fix,
                        parallel_workers=args.parallel,
                        auto_approve=args.yes or not args.prompt,
                        research_depth=args.research_depth,
                        enable_prompt_optimization=enable_prompt_optimization,
                        auto_optimize_prompt=auto_optimize_prompt,
                        enable_context_guard=enable_context_guard,
                        context_guard_interactive=context_guard_interactive,
                        context_guard_threshold=context_guard_threshold,
                        resume=True,
                        resume_plan=True,
                    )
                    if not result.success:
                        sys.exit(1)
                    sys.exit(0)

                if args.resume_continue:
                    # Reset stopped tasks to pending so they can be executed
                    for task in plan.tasks:
                        if task.status == TaskStatus.STOPPED:
                            task.status = TaskStatus.PENDING
    
                    # Use concurrent execution if parallel > 1, otherwise sequential
                    debug_logger.log_workflow_phase("execution", {
                        "mode": "concurrent" if args.parallel > 1 else "sequential",
                        "workers": args.parallel,
                        "task_count": len(plan.tasks)
                    })
                    tools = get_available_tools()
                    if args.parallel > 1:
                        concurrent_execution_mode(
                            plan,
                            max_workers=args.parallel,
                            auto_approve=args.yes or not args.prompt,
                            tools=tools,
                            enable_action_review=args.action_review,
                            state_manager=state_manager,
                        )
                    else:
                        execution_mode(
                            plan,
                            auto_approve=args.yes or not args.prompt,
                            tools=tools,
                            enable_action_review=args.action_review,
                            state_manager=state_manager,
                        )
    
                    # Validation phase
                    enable_validation = args.validate and not args.no_validate
                    if enable_validation:
                        debug_logger.log_workflow_phase("validation", {"resumed": True})
                        validation_report = validate_execution(
                            plan,
                            "Resumed execution",
                            run_tests=True,
                            run_linter=True,
                            check_syntax=True,
                            enable_auto_fix=args.auto_fix
                        )
    
                        debug_logger.log("main", "VALIDATION_RESULT", {
                            "status": validation_report.overall_status.value,
                            "rollback_recommended": validation_report.rollback_recommended
                        })
    
                        if validation_report.overall_status == ValidationStatus.FAILED:
                            print("\n❌ Validation failed. Review issues above.")
                            if validation_report.rollback_recommended:
                                print("   Consider: git checkout -- . (to revert changes)")
                            sys.exit(1)
                        elif validation_report.overall_status == ValidationStatus.PASSED_WITH_WARNINGS:
                            print("\n[!] Validation passed with warnings.")
                        else:
                            print("\n✅ Validation passed successfully.")
    
                    sys.exit(0)

            except FileNotFoundError:
                print(f"✗ Checkpoint file not found: {args.resume}")
                print("\nUse --list-checkpoints to see available checkpoints.")
                sys.exit(1)
            except Exception as e:
                print(f"✗ Failed to load checkpoint: {e}")
                sys.exit(1)
        if args.tui and args.task:
            # TUI is inherently interactive; treat one-shot tasks as the initial REPL command
            # so the user can see scrollback and keep the prompt at the bottom.
            initial_command = " ".join(args.task)
            args.repl = True
            args.task = []

        if args.repl or not args.task:
            debug_logger.log_workflow_phase("repl", {})
            repl_mode(
                force_tui=args.tui,
                init_logs=buffered_logs if use_tui_main else None,
                initial_command=initial_command,
                resume=resume_context,
                resume_plan=resume_plan,
            )
        else:
            task_description = " ".join(args.task)
            debug_logger.log("main", "TASK_DESCRIPTION", {"task": task_description})

            # Handle --no-orchestrate flag
            if args.no_orchestrate:
                args.orchestrate = False

            # Orchestrator mode - full multi-agent coordination
            if args.orchestrate:
                debug_logger.log_workflow_phase("orchestrate", {
                    "task": task_description,
                    "learning": args.learn,
                    "research": args.research
                })
                result = run_orchestrated(
                    task_description,
                    config.ROOT,
                    enable_learning=args.learn,
                    enable_research=args.research,
                    enable_review=args.review and not args.no_review,
                    enable_validation=args.validate and not args.no_validate,
                    review_strictness=args.review_strictness,
                    enable_action_review=args.action_review,
                    enable_auto_fix=args.auto_fix,
                    parallel_workers=args.parallel,
                    auto_approve=args.yes or not args.prompt,
                    research_depth=args.research_depth,
                    enable_prompt_optimization=enable_prompt_optimization,
                    auto_optimize_prompt=auto_optimize_prompt,
                    enable_context_guard=enable_context_guard,
                    context_guard_interactive=context_guard_interactive,
                    context_guard_threshold=context_guard_threshold,
                    resume=resume_context,
                    resume_plan=resume_plan,
                )
                if not result.success:
                    sys.exit(1)
                sys.exit(0)

            # Standard mode - manual agent coordination
            debug_logger.log_workflow_phase("planning", {"task": task_description})
            plan = planning_mode(
                task_description,
                max_plan_tasks=config.MAX_PLAN_TASKS,
                max_planning_iterations=config.MAX_PLANNING_TOOL_ITERATIONS,
            )
            state_manager = StateManager(plan)
            debug_logger.log("main", "PLAN_GENERATED", {
                "task_count": len(plan.tasks),
                "tasks": [{"id": t.id, "description": t.description[:100]} for t in plan.tasks]
            })

            # Review phase - Review Agent validates the plan
            enable_review = args.review and not args.no_review
            if enable_review:
                debug_logger.log_workflow_phase("review", {
                    "strictness": args.review_strictness
                })
                strictness = ReviewStrictness(args.review_strictness)
                review = review_execution_plan(
                    plan,
                    task_description,
                    strictness=strictness,
                    auto_approve_low_risk=True
                )

                debug_logger.log("main", "REVIEW_DECISION", {
                    "decision": review.decision.value,
                    "risk_level": review.risk_level.value if hasattr(review, 'risk_level') else None
                })

                # Handle review decision
                if review.decision == ReviewDecision.REJECTED:
                    print("\n❌ Plan rejected by review agent.")
                    if args.prompt:
                        print("   The plan has critical issues that should be addressed.")
                        response = input("Continue anyway? (y/N): ")
                        if response.lower() != 'y':
                            print("Aborted by user")
                            sys.exit(1)
                    else:
                        print("   [!] WARNING: Proceeding despite rejection (autonomous mode)")
                        print("   The plan has critical issues. Use --prompt to review or --no-review to disable.")
                elif review.decision == ReviewDecision.REQUIRES_CHANGES:
                    print("\n[!] Plan requires changes. Review the issues above.")
                    if args.prompt:
                        response = input("Continue anyway? (y/N): ")
                        if response.lower() != 'y':
                            print("Aborted by user")
                            sys.exit(1)
                    else:
                        print("Continuing with warnings (use --prompt to review)...")
                elif review.decision == ReviewDecision.APPROVED_WITH_SUGGESTIONS:
                    print("\n✅ Plan approved with suggestions. Review recommendations above.")
                else:
                    print("\n✅ Plan approved by review agent.")

            # Use concurrent execution if parallel > 1, otherwise sequential
            debug_logger.log_workflow_phase("execution", {
                "mode": "concurrent" if args.parallel > 1 else "sequential",
                "workers": args.parallel,
                "task_count": len(plan.tasks)
            })
            tools = get_available_tools()
            if args.parallel > 1:
                concurrent_execution_mode(
                    plan,
                    max_workers=args.parallel,
                    auto_approve=args.yes or not args.prompt,
                    tools=tools,
                    enable_action_review=args.action_review,
                    state_manager=state_manager,
                )
            else:
                execution_mode(
                    plan,
                    auto_approve=args.yes or not args.prompt,
                    tools=tools,
                    enable_action_review=args.action_review,
                    state_manager=state_manager,
                )

            # Validation phase - Validation Agent verifies results
            enable_validation = args.validate and not args.no_validate
            if enable_validation:
                debug_logger.log_workflow_phase("validation", {})
                validation_report = validate_execution(
                    plan,
                    task_description,
                    run_tests=True,
                    run_linter=True,
                    check_syntax=True,
                    enable_auto_fix=args.auto_fix
                )

                debug_logger.log("main", "VALIDATION_RESULT", {
                    "status": validation_report.overall_status.value,
                    "rollback_recommended": validation_report.rollback_recommended
                })

                if validation_report.overall_status == ValidationStatus.FAILED:
                    print("\n❌ Validation failed. Review issues above.")
                    if validation_report.rollback_recommended:
                        print("   Consider: git checkout -- . (to revert changes)")
                    sys.exit(1)
                elif validation_report.overall_status == ValidationStatus.PASSED_WITH_WARNINGS:
                    print("\n[!] Validation passed with warnings.")
                else:
                    print("\n✅ Validation passed successfully.")

    except KeyboardInterrupt:
        # Log the interrupt event
        debug_logger.log("main", "USER_INTERRUPT", {}, "WARNING")
        # Attempt to persist state if a plan has been created
        try:
            current_manager = locals().get("state_manager") or globals().get("state_manager")
            current_plan = locals().get("plan") or globals().get("plan")

            if current_manager is None and current_plan is not None:
                current_manager = StateManager(current_plan)

            if current_manager is not None:
                current_manager.on_interrupt()
        except Exception as exc:  # pragma: no cover – ensure interrupt handling never fails
            print(f"  Warning: could not save checkpoint on interrupt ({exc})")
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        debug_logger.log_error("main", e, {"context": "main execution loop"})
        raise
    finally:
        try:
            if mcp_processes:
                stop_mcp_servers(mcp_processes)
        except Exception:
            pass
        # Close the debug logger
        debug_logger.close()


if __name__ == "__main__":
    main()
