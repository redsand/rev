#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry point for rev CLI."""

import sys
import argparse

from . import config
from .cache import initialize_caches
from .execution import planning_mode, execution_mode, concurrent_execution_mode
from .execution.reviewer import review_execution_plan, ReviewStrictness, ReviewDecision
from .terminal import repl_mode


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

    args = parser.parse_args()

    # Update config globals for ollama_chat function
    config.OLLAMA_MODEL = args.model
    config.OLLAMA_BASE_URL = args.base_url

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
        if args.repl or not args.task:
            repl_mode()
        else:
            task_description = " ".join(args.task)
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
                    print("\n❌ Plan rejected by review agent. Please revise your request.")
                    sys.exit(1)
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
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
