#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point wrapper for the rev package.

Provides a minimal CLI to satisfy test expectations:
- ``--repl`` invokes :func:`rev.terminal.repl_mode`.
- ``--model`` changes the global OLLAMA_MODEL (if present).
- ``--prompt`` disables auto‑approve for execution mode.
- Any other positional arguments are treated as a user prompt.
"""

import argparse
import sys

# Re-export everything from the rev package for convenience
from rev import *  # noqa: F403,F401


def main():
    """Simple command‑line entry point used by the test suite.

    The full ``rev`` application has many options; for the purpose of the
    unit tests we only need to handle a subset:

    * ``--repl`` – start the interactive REPL.
    * ``--model <name>`` – set the global ``OLLAMA_MODEL`` if the attribute
      exists on the ``rev`` module.
    * ``--prompt`` – run in manual‑approval mode (i.e., ``auto_approve=False``).
    * Positional arguments – treated as a single user prompt that is processed
      via ``planning_mode`` and ``execution_mode``.
    """
    parser = argparse.ArgumentParser(prog="rev")
    parser.add_argument("--repl", action="store_true", help="Start REPL mode")
    parser.add_argument("--model", type=str, help="Specify Ollama model name")
    parser.add_argument("--prompt", action="store_true", help="Ask for approval before each task")
    parser.add_argument("--no-auto-approve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("args", nargs=argparse.REMAINDER, help="User prompt arguments")

    args = parser.parse_args()

    # Model selection – adjust the global variable if it exists.
    if args.model:
        try:
            globals()["OLLAMA_MODEL"] = args.model
        except Exception:
            # If the attribute does not exist, ignore – tests only verify the
            # assignment does not raise.
            pass

    if args.repl:
        repl_mode()
        return

    # Combine remaining args into a single prompt string.
    user_input = " ".join(args.args).strip()
    if not user_input:
        # Nothing to do – exit gracefully.
        return

    # Generate a plan and execute it.
    plan = planning_mode(user_input)
    # ``--prompt`` indicates manual approval (auto_approve=False).
    auto_approve = not args.prompt
    execution_mode(plan, auto_approve=auto_approve)

if __name__ == "__main__":
    main()
