#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry point for rev CLI."""

import sys
import argparse

from . import config
from .cache import initialize_caches
from .execution import planning_mode, execution_mode, concurrent_execution_mode
from .execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from .execution.validator import validate_execution, ValidationStatus
from .execution.orchestrator import run_orchestrated
from .terminal import repl_mode
from .models.task import ExecutionPlan


def main():
    """Main entry point for the rev CLI."""
    # Initialize cache system
    cache_dir = config.ROOT / ".rev_cache"
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
        "--prompt",
        action="store_true",
        help="Prompt for approval before execution (default: auto-approve)"
    )
    parser.add_argument(
        "-j", "--parallel",
        type=int,
        default=2,
        metavar="N",
        help="Number of concurrent tasks to run in parallel (default: 2, use 1 for sequential)"
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
        help="Enable orchestrator mode - coordinates all agents for maximum autonomy"
    )
    parser.add_argument(
        "--research",
        action="store_true",
        help="Enable research agent for pre-planning codebase exploration"
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
        metavar="CHECKPOINT",
        help="Resume execution from a checkpoint file"
    )
    parser.add_argument(
        "--list-checkpoints",
        action="store_true",
        help="List all available checkpoints"
    )

    args = parser.parse_args()

    # Update config globals for ollama_chat function
    config.OLLAMA_MODEL = args.model
    config.OLLAMA_BASE_URL = args.base_url

    # Handle list-checkpoints command
    if args.list_checkpoints:
        print("rev - Available Checkpoints\n")
        checkpoints = ExecutionPlan.list_checkpoints()
        if not checkpoints:
            print("No checkpoints found.")
            print(f"Checkpoints are saved in .rev_checkpoints/ directory when execution is interrupted.")
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
        print("  ℹ️  Autonomous mode: destructive operations will prompt for confirmation")
    print()

    try:
        # Handle resume command
        if args.resume:
            print(f"Resuming from checkpoint: {args.resume}\n")
            try:
                plan = ExecutionPlan.load_checkpoint(args.resume)
                print(f"✓ Checkpoint loaded successfully")
                print(f"  {plan.get_summary()}\n")

                # Reset stopped tasks to pending so they can be executed
                for task in plan.tasks:
                    if task.status.value == "stopped":
                        task.status = task.status.__class__("pending")

                # Use concurrent execution if parallel > 1, otherwise sequential
                if args.parallel > 1:
                    concurrent_execution_mode(
                        plan,
                        max_workers=args.parallel,
                        auto_approve=not args.prompt,
                        enable_action_review=args.action_review
                    )
                else:
                    execution_mode(
                        plan,
                        auto_approve=not args.prompt,
                        enable_action_review=args.action_review
                    )

                # Validation phase
                enable_validation = args.validate and not args.no_validate
                if enable_validation:
                    validation_report = validate_execution(
                        plan,
                        "Resumed execution",
                        run_tests=True,
                        run_linter=True,
                        check_syntax=True,
                        enable_auto_fix=args.auto_fix
                    )

                    if validation_report.overall_status == ValidationStatus.FAILED:
                        print("\n❌ Validation failed. Review issues above.")
                        if validation_report.rollback_recommended:
                            print("   Consider: git checkout -- . (to revert changes)")
                        sys.exit(1)
                    elif validation_report.overall_status == ValidationStatus.PASSED_WITH_WARNINGS:
                        print("\n⚠️  Validation passed with warnings.")
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
            repl_mode()
        else:
            task_description = " ".join(args.task)

            # Orchestrator mode - full multi-agent coordination
            if args.orchestrate:
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
                    auto_approve=not args.prompt,
                    research_depth=args.research_depth
                )
                if not result.success:
                    sys.exit(1)
                sys.exit(0)

            # Standard mode - manual agent coordination
            plan = planning_mode(task_description)

            # Review phase - Review Agent validates the plan
            enable_review = args.review and not args.no_review
            if enable_review:
                strictness = ReviewStrictness(args.review_strictness)
                review = review_execution_plan(
                    plan,
                    task_description,
                    strictness=strictness,
                    auto_approve_low_risk=True
                )

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
                        print("   ⚠️  WARNING: Proceeding despite rejection (autonomous mode)")
                        print("   The plan has critical issues. Use --prompt to review or --no-review to disable.")
                elif review.decision == ReviewDecision.REQUIRES_CHANGES:
                    print("\n⚠️  Plan requires changes. Review the issues above.")
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
            if args.parallel > 1:
                concurrent_execution_mode(
                    plan,
                    max_workers=args.parallel,
                    auto_approve=not args.prompt,
                    enable_action_review=args.action_review
                )
            else:
                execution_mode(
                    plan,
                    auto_approve=not args.prompt,
                    enable_action_review=args.action_review
                )

            # Validation phase - Validation Agent verifies results
            enable_validation = args.validate and not args.no_validate
            if enable_validation:
                validation_report = validate_execution(
                    plan,
                    task_description,
                    run_tests=True,
                    run_linter=True,
                    check_syntax=True,
                    enable_auto_fix=args.auto_fix
                )

                if validation_report.overall_status == ValidationStatus.FAILED:
                    print("\n❌ Validation failed. Review issues above.")
                    if validation_report.rollback_recommended:
                        print("   Consider: git checkout -- . (to revert changes)")
                    sys.exit(1)
                elif validation_report.overall_status == ValidationStatus.PASSED_WITH_WARNINGS:
                    print("\n⚠️  Validation passed with warnings.")
                else:
                    print("\n✅ Validation passed successfully.")

    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
