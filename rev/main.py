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


def main():
    """Main entry point for the rev CLI."""
    # Apply any saved configuration overrides before parsing arguments
    apply_saved_settings()

    # Ensure rev data directory exists
    config.REV_DIR.mkdir(parents=True, exist_ok=True)

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
        "--model",
        default=config.OLLAMA_MODEL,
        help=f"Ollama model (default: {config.OLLAMA_MODEL})"
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
        help="Number of concurrent tasks to run in parallel (forced to 1; parallel execution is disabled)"
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
        help="Execution mode: 'linear' (traditional sequential), 'sub-agent' (dispatch to specialized agents). 'inline' is alias for 'linear'. Default: from REV_EXECUTION_MODE env var or 'linear'"
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
        help="Resume execution from a checkpoint file (defaults to latest if no path provided)"
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
        "-v",
        "--version",
        action="store_true",
        help="Show rev version information and exit",
    )


    args = parser.parse_args()

    # Enforce single-worker execution regardless of CLI input
    if args.parallel != 1:
        print(f"⚠️ Parallel execution is disabled. Forcing --parallel=1 (requested {args.parallel}).")
        args.parallel = 1

    # Initialize debug logging if requested
    debug_logger = DebugLogger.initialize(enabled=args.debug)
    if args.debug:
        print(f"Debug logging enabled: {debug_logger.log_file_path}")

    # Update config globals for ollama_chat function
    config.set_model(args.model)
    config.OLLAMA_BASE_URL = args.base_url

    # Set execution mode if provided
    if args.execution_mode:
        config.set_execution_mode(args.execution_mode)

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

    context_guard_threshold = args.context_guard_threshold

    if args.version:
        from rev.versioning import build_version_output

        print(build_version_output(config.OLLAMA_MODEL, config.get_system_info_cached()))
        sys.exit(0)


    if args.clean:
        print("Cleaning temporary files, caches, and logs...")
        if config.REV_DIR.exists():
            shutil.rmtree(config.REV_DIR)
            print(f"Removed {config.REV_DIR}")
        print("Clean complete.")
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


    print(f"rev - CI/CD Agent")
    print(f"Model: {config.OLLAMA_MODEL}")
    print(f"Ollama: {config.OLLAMA_BASE_URL}")
    print(f"Repository: {config.ROOT}")
    if args.parallel > 1:
        print(f"Parallel execution: {args.parallel} concurrent tasks")
    if not args.prompt:
        print("  [i] Autonomous mode: destructive operations will prompt for confirmation")
    print()

    state_manager: Optional[StateManager] = None

    try:
        # Handle resume command
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
            print(f"Resuming from checkpoint: {checkpoint_path}\n")
            try:
                plan = ExecutionPlan.load_checkpoint(checkpoint_path)
                state_manager = StateManager(plan)
                print(f"✓ Checkpoint loaded successfully")
                print(f"  {plan.get_summary()}\n")
                debug_logger.log("main", "CHECKPOINT_LOADED", {
                    "checkpoint": args.resume,
                    "task_count": len(plan.tasks),
                    "summary": plan.get_summary()
                })

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
        if args.repl or not args.task:
            debug_logger.log_workflow_phase("repl", {})
            repl_mode()
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
                    context_guard_threshold=context_guard_threshold
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
            print(f"⚠️  Warning: could not save checkpoint on interrupt ({exc})")
        print("\n\nAborted by user")
        sys.exit(1)
    except Exception as e:
        debug_logger.log_error("main", e, {"context": "main execution loop"})
        raise
    finally:
        # Close the debug logger
        debug_logger.close()


if __name__ == "__main__":
    main()
