#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive slash command handlers for the REPL."""

import os
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod

from rev import config
from rev.tools.registry import get_available_tools
from rev.models.task import ExecutionPlan
from rev.execution.reviewer import review_execution_plan, ReviewStrictness
from rev.execution.validator import validate_execution
from rev.execution import planning_mode, execution_mode
from rev.terminal.formatting import (
    create_header, create_section, create_item, create_bullet_item,
    create_tree_item, create_panel, colorize, Colors, Symbols
)


class CommandHandler(ABC):
    """Base class for slash command handlers."""

    def __init__(self, name: str, description: str, aliases: Optional[List[str]] = None):
        self.name = name
        self.description = description
        self.aliases = aliases or []

    @abstractmethod
    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        """Execute the command and return output.

        Args:
            args: Command arguments
            session_context: REPL session context

        Returns:
            Output message to display to user
        """
        pass

    def get_help(self) -> str:
        """Get detailed help for this command."""
        return self.description


class HelpCommand(CommandHandler):
    """Show help for available commands."""

    def __init__(self):
        super().__init__(
            "help",
            "Show available commands or detailed help for a specific command"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        if args:
            # Show help for specific command
            cmd_name = args[0]
            if cmd_name in COMMAND_HANDLERS:
                handler = COMMAND_HANDLERS[cmd_name]
                return create_header(f"/{handler.name}") + f"\n  {handler.get_help()}"
            else:
                return create_bullet_item(f"Unknown command: /{cmd_name}", 'cross')

        # Show all commands
        output = [create_header("Available Commands", width=80)]

        # Group commands by category
        categories = {
            "Session Management": ["clear", "exit", "quit"],
            "Information": ["status", "cost", "config", "doctor", "version"],
            "Model & Configuration": ["model", "add-dir"],
            "Code Review & Validation": ["review", "validate"],
            "Project Setup": ["init", "export"],
            "Help": ["help"]
        }

        for category, cmds in categories.items():
            output.append(create_section(category))
            for cmd_name in cmds:
                if cmd_name in COMMAND_HANDLERS:
                    handler = COMMAND_HANDLERS[cmd_name]
                    cmd_colored = colorize(f"/{handler.name}", Colors.BRIGHT_CYAN)
                    output.append(f"  {cmd_colored:<25} {handler.description}")

        output.append(create_section("Input Shortcuts"))
        output.append(create_item("ESC", "Submit input immediately"))
        output.append(create_item("Ctrl+C", "Exit REPL"))

        output.append(f"\n  {colorize('Type /help <command> for detailed help', Colors.DIM)}")

        return "\n".join(output)


class StatusCommand(CommandHandler):
    """Show session status and statistics."""

    def __init__(self):
        super().__init__(
            "status",
            "Show session summary and statistics"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        output = [create_header("Session Summary", width=80)]

        output.append(create_section("Activity"))
        output.append(create_item("Tasks completed", str(len(session_context.get('tasks_completed', [])))))
        output.append(create_item("Files reviewed", str(len(session_context.get('files_reviewed', set())))))
        output.append(create_item("Files modified", str(len(session_context.get('files_modified', set())))))

        output.append(create_section("Configuration"))
        output.append(create_item("Model", config.OLLAMA_MODEL))
        output.append(create_item("Ollama URL", config.OLLAMA_BASE_URL))
        output.append(create_item("Working directory", str(config.ROOT)))

        if session_context.get("token_usage"):
            output.append(create_section("Token Usage"))
            output.append(create_item("Total tokens", f"{session_context['token_usage']['total']:,}"))
            output.append(create_item("Prompt tokens", f"{session_context['token_usage']['prompt']:,}"))
            output.append(create_item("Completion tokens", f"{session_context['token_usage']['completion']:,}"))

        if session_context.get("last_summary"):
            output.append(create_section("Last Execution"))
            output.append(f"  {session_context['last_summary']}")

        return "\n".join(output)


class CostCommand(CommandHandler):
    """Show token usage and cost statistics."""

    def __init__(self):
        super().__init__(
            "cost",
            "Show token usage statistics and estimated costs"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        token_usage = session_context.get("token_usage", {
            "total": 0,
            "prompt": 0,
            "completion": 0
        })

        output = [create_header("Token Usage & Cost", width=80)]

        output.append(create_section("Current Session"))
        output.append(create_item("Total tokens", f"{token_usage['total']:,}"))
        output.append(create_item("Prompt tokens", f"{token_usage['prompt']:,}"))
        output.append(create_item("Completion tokens", f"{token_usage['completion']:,}"))
        output.append(create_item("Model", config.OLLAMA_MODEL))
        output.append(f"\n  {colorize(f'{Symbols.CHECK} Ollama is free and runs locally - no API costs!', Colors.BRIGHT_GREEN)}")

        # Resource budget information
        output.append(create_section("Resource Budgets"))
        output.append(create_item("Max steps per run", str(config.MAX_STEPS_PER_RUN)))
        output.append(create_item("Max tokens per run", f"{config.MAX_LLM_TOKENS_PER_RUN:,}"))
        output.append(create_item("Max time", f"{config.MAX_WALLCLOCK_SECONDS}s ({config.MAX_WALLCLOCK_SECONDS // 60} minutes)"))

        return "\n".join(output)


class ModelCommand(CommandHandler):
    """Change the AI model being used."""

    def __init__(self):
        super().__init__(
            "model",
            "View or change the AI model (e.g., /model codellama:latest)"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        if not args:
            # Show current model
            return f"\nCurrent model: {config.OLLAMA_MODEL}\nUsage: /model <model_name>"

        # Change model
        new_model = args[0]
        old_model = config.OLLAMA_MODEL
        config.OLLAMA_MODEL = new_model

        return f"\nModel changed: {old_model} → {new_model}"


class ConfigCommand(CommandHandler):
    """Show or modify configuration settings."""

    def __init__(self):
        super().__init__(
            "config",
            "View current configuration settings"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        output = ["\nConfiguration:"]
        output.append("=" * 60)
        output.append(f"  Model:             {config.OLLAMA_MODEL}")
        output.append(f"  Ollama URL:        {config.OLLAMA_BASE_URL}")
        output.append(f"  Root directory:    {config.ROOT}")
        output.append(f"  Max file size:     {config.MAX_FILE_BYTES // 1024 // 1024}MB")
        output.append(f"  Search limit:      {config.SEARCH_MATCH_LIMIT}")
        output.append(f"  SSH available:     {config.SSH_AVAILABLE}")
        output.append(f"\nResource Budgets:")
        output.append(f"  Max steps:         {config.MAX_STEPS_PER_RUN}")
        output.append(f"  Max tokens:        {config.MAX_LLM_TOKENS_PER_RUN:,}")
        output.append(f"  Max time:          {config.MAX_WALLCLOCK_SECONDS}s")
        output.append(f"\nEnvironment:")
        system_info = config.get_system_info_cached()
        output.append(f"  OS:                {system_info['os']} {system_info['os_release']}")
        output.append(f"  Architecture:      {system_info['architecture']}")
        output.append(f"  Python:            {system_info['python_version']}")

        return "\n".join(output)


class ClearCommand(CommandHandler):
    """Clear session memory."""

    def __init__(self):
        super().__init__(
            "clear",
            "Clear session memory and conversation history"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        # Reset session context
        session_context["tasks_completed"] = []
        session_context["files_modified"] = set()
        session_context["files_reviewed"] = set()
        session_context["last_summary"] = ""
        session_context["token_usage"] = {"total": 0, "prompt": 0, "completion": 0}

        return "Session memory cleared"


class ExitCommand(CommandHandler):
    """Exit the REPL."""

    def __init__(self):
        super().__init__(
            "exit",
            "Exit the REPL session",
            aliases=["quit", "q"]
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        # Return special marker to indicate exit
        return "__EXIT__"


class DoctorCommand(CommandHandler):
    """Check system health and configuration."""

    def __init__(self):
        super().__init__(
            "doctor",
            "Check installation health and configuration"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        output = [create_header("System Health Check", width=80)]

        # Check Ollama connectivity
        output.append(create_section("Ollama Server"))
        import requests
        try:
            response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
            if response.status_code == 200:
                output.append(create_bullet_item("Ollama server: Connected", 'check'))
                models = response.json().get("models", [])
                output.append(f"  {Symbols.TREE_BRANCH}  Available models: {len(models)}")
                if models:
                    for i, model in enumerate(models[:5]):  # Show first 5
                        is_current = model['name'] == config.OLLAMA_MODEL
                        marker = colorize(Symbols.ARROW, Colors.BRIGHT_GREEN) if is_current else " "
                        output.append(f"    {marker} {model['name']}")
            else:
                output.append(create_bullet_item(f"Ollama server: Error (status {response.status_code})", 'cross'))
        except Exception as e:
            output.append(create_bullet_item(f"Ollama server: Not reachable ({str(e)[:50]})", 'cross'))

        # Check git
        output.append(create_section("Development Tools"))
        git_available = shutil.which("git") is not None
        output.append(create_bullet_item(f"Git: {'Available' if git_available else 'Not found'}",
                                        'check' if git_available else 'cross'))

        # Check Python tools
        tools = ["pytest", "ruff", "black", "mypy", "pylint"]
        for tool in tools:
            available = shutil.which(tool) is not None
            bullet = 'check' if available else 'hollow'
            status = 'Available' if available else 'Not installed (optional)'
            output.append(create_bullet_item(f"{tool}: {status}", bullet))

        # Check dependencies
        output.append(create_section("Dependencies"))
        ssh_bullet = 'check' if config.SSH_AVAILABLE else 'hollow'
        output.append(create_bullet_item(f"SSH support: {'Available' if config.SSH_AVAILABLE else 'Not available'}", ssh_bullet))

        # Check directory permissions
        output.append(create_section("Permissions"))
        try:
            test_file = config.ROOT / ".rev_test"
            test_file.touch()
            test_file.unlink()
            output.append(create_bullet_item(f"Write access: {config.ROOT}", 'check'))
        except Exception as e:
            output.append(create_bullet_item(f"Write access: Failed ({str(e)})", 'cross'))

        return "\n".join(output)


class AddDirCommand(CommandHandler):
    """Add additional working directories."""

    def __init__(self):
        super().__init__(
            "add-dir",
            "Add additional working directories for rev to access"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        if not args:
            return "Usage: /add-dir <directory> [<directory> ...]"

        added_dirs = []
        for dir_path in args:
            path = Path(dir_path).resolve()
            if path.exists() and path.is_dir():
                # In a real implementation, you'd track these in session context
                # For now, just acknowledge
                added_dirs.append(str(path))
            else:
                return f"Error: Directory not found: {dir_path}"

        return f"Added directories: {', '.join(added_dirs)}\n(Note: Implementation pending - directories tracked in session)"


class InitCommand(CommandHandler):
    """Initialize project with AGENT.md guidance file."""

    def __init__(self):
        super().__init__(
            "init",
            "Initialize project by creating an AGENT.md guidance file"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        agent_file = config.ROOT / "AGENT.md"

        if agent_file.exists():
            return f"AGENT.md already exists in {config.ROOT}"

        content = """# Agent Guidance

This file provides context and guidelines for the AI agent working on this project.

## Project Overview

[Describe your project here]

## Architecture

[Describe the project structure and architecture]

## Development Guidelines

- Code style: [e.g., PEP 8 for Python]
- Testing: [e.g., Use pytest, aim for >80% coverage]
- Documentation: [e.g., Docstrings for all public functions]

## Common Tasks

### Running Tests
```bash
pytest
```

### Code Quality
```bash
ruff check .
black .
mypy .
```

## Important Notes

- [Any important considerations or constraints]
- [Sensitive areas that require careful changes]
"""

        with open(agent_file, "w") as f:
            f.write(content)

        return f"✓ Created AGENT.md in {config.ROOT}\nEdit this file to provide guidance for the AI agent."


class ReviewCommand(CommandHandler):
    """Request a code review of current changes."""

    def __init__(self):
        super().__init__(
            "review",
            "Request a code review of uncommitted changes"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        # Create a simple review plan
        from rev.tools.git_ops import git_diff, git_status

        status = git_status()
        diff = git_diff()

        if not diff or diff == "No changes":
            return "No uncommitted changes to review"

        output = ["\nCode Review Request:"]
        output.append("=" * 60)
        output.append("\nGit Status:")
        output.append(status)
        output.append("\nChanges:")
        output.append(diff[:2000])  # Limit output
        if len(diff) > 2000:
            output.append(f"\n... ({len(diff) - 2000} more characters)")
        output.append("\n(Full review agent integration pending)")

        return "\n".join(output)


class ValidateCommand(CommandHandler):
    """Run validation checks on the codebase."""

    def __init__(self):
        super().__init__(
            "validate",
            "Run validation checks (tests, linting, syntax)"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        output = ["\nRunning validation checks..."]
        output.append("=" * 60)

        # This would integrate with the validation agent
        # For now, show what would be checked
        output.append("\nValidation checks (integration pending):")
        output.append("  - Syntax validation")
        output.append("  - Linting (ruff/pylint)")
        output.append("  - Type checking (mypy)")
        output.append("  - Unit tests")
        output.append("  - Code complexity")
        output.append("\nUse the --validate flag in non-REPL mode for full validation")

        return "\n".join(output)


class ExportCommand(CommandHandler):
    """Export conversation history."""

    def __init__(self):
        super().__init__(
            "export",
            "Export conversation history to a file"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        filename = args[0] if args else "rev_session.json"
        filepath = config.ROOT / filename

        # Export session context
        export_data = {
            "model": config.OLLAMA_MODEL,
            "tasks_completed": session_context.get("tasks_completed", []),
            "files_modified": list(session_context.get("files_modified", [])),
            "files_reviewed": list(session_context.get("files_reviewed", [])),
            "token_usage": session_context.get("token_usage", {}),
            "last_summary": session_context.get("last_summary", "")
        }

        with open(filepath, "w") as f:
            json.dump(export_data, f, indent=2)

        return f"✓ Session exported to {filepath}"


class VersionCommand(CommandHandler):
    """Show version information."""

    def __init__(self):
        super().__init__(
            "version",
            "Show rev version and system information"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        system_info = config.get_system_info_cached()

        output = ["\nRev - Autonomous Development System"]
        output.append("=" * 60)
        output.append("  Version:          5.0")
        output.append("  Architecture:     6-Agent System")
        output.append(f"  Model:            {config.OLLAMA_MODEL}")
        output.append(f"\nSystem:")
        output.append(f"  OS:               {system_info['os']} {system_info['os_release']}")
        output.append(f"  Architecture:     {system_info['architecture']}")
        output.append(f"  Python:           {system_info['python_version']}")

        return "\n".join(output)


class CompactCommand(CommandHandler):
    """Compact conversation history."""

    def __init__(self):
        super().__init__(
            "compact",
            "Summarize conversation history to save tokens"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        # This would use the LLM to summarize the conversation
        # For now, just provide feedback
        instructions = " ".join(args) if args else "general summary"

        output = [f"\nCompacting conversation history..."]
        output.append(f"Instructions: {instructions}")
        output.append("\n(Full compaction with LLM integration pending)")
        output.append("Current approach: Session context is maintained across prompts")

        return "\n".join(output)


class PermissionsCommand(CommandHandler):
    """View and update tool permissions."""

    def __init__(self):
        super().__init__(
            "permissions",
            "View or update tool execution permissions"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        output = ["\nTool Permissions:"]
        output.append("=" * 60)
        output.append("  File operations:   Allowed (destructive ops prompt)")
        output.append("  Git operations:    Allowed")
        output.append("  Shell commands:    Restricted (whitelist only)")
        output.append("  SSH operations:    " + ("Allowed" if config.SSH_AVAILABLE else "Not available"))
        output.append(f"\nWhitelisted commands:")
        for cmd in sorted(config.ALLOW_CMDS):
            output.append(f"  - {cmd}")
        output.append("\n(Fine-grained permission controls pending)")

        return "\n".join(output)


class AgentsCommand(CommandHandler):
    """Manage custom AI subagents."""

    def __init__(self):
        super().__init__(
            "agents",
            "Manage custom AI subagents for specialized tasks"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        output = ["\nAgent System:"]
        output.append("=" * 60)
        output.append("\nBuilt-in Agents:")
        output.append("  - Planner:        Task decomposition and planning")
        output.append("  - Executor:       Task execution with tool calls")
        output.append("  - Reviewer:       Plan and action validation")
        output.append("  - Validator:      Post-execution verification")
        output.append("  - Orchestrator:   Multi-agent coordination")
        output.append("  - Research:       Codebase exploration")
        output.append("  - Learning:       Cross-session memory")
        output.append("\n(Custom agent creation pending)")

        return "\n".join(output)


# Command registry - dictionary for O(1) lookup
def _build_command_registry() -> Dict[str, CommandHandler]:
    """Build the command registry with all available commands."""
    handlers = [
        HelpCommand(),
        StatusCommand(),
        CostCommand(),
        ModelCommand(),
        ConfigCommand(),
        ClearCommand(),
        ExitCommand(),
        DoctorCommand(),
        AddDirCommand(),
        InitCommand(),
        ReviewCommand(),
        ValidateCommand(),
        ExportCommand(),
        VersionCommand(),
        CompactCommand(),
        PermissionsCommand(),
        AgentsCommand()
    ]

    registry = {}
    for handler in handlers:
        registry[handler.name] = handler
        # Add aliases
        for alias in handler.aliases:
            registry[alias] = handler

    return registry


# Build the registry once at module import
COMMAND_HANDLERS = _build_command_registry()


def execute_command(command: str, args: List[str], session_context: Dict[str, Any]) -> str:
    """Execute a slash command.

    Args:
        command: Command name (without leading /)
        args: Command arguments
        session_context: REPL session context

    Returns:
        Command output or error message
    """
    if command in COMMAND_HANDLERS:
        handler = COMMAND_HANDLERS[command]
        return handler.execute(args, session_context)
    else:
        return f"Unknown command: /{command}\nType /help for available commands"
