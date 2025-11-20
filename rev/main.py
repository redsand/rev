#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry point for rev CLI."""

import sys
import argparse

from . import config
from .cache import initialize_caches
from .execution import planning_mode, execution_mode, concurrent_execution_mode
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
            # Use concurrent execution if parallel > 1, otherwise sequential
            if args.parallel > 1:
                concurrent_execution_mode(plan, max_workers=args.parallel, auto_approve=not args.prompt)
            else:
                execution_mode(plan, auto_approve=not args.prompt)
    except KeyboardInterrupt:
        print("\n\nAborted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
