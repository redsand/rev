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
from rev.versioning import build_version_output
from rev.tools.registry import get_available_tools
from rev.models.task import ExecutionPlan
from rev.execution.reviewer import review_execution_plan, ReviewStrictness
from rev.execution.validator import validate_execution
from rev.execution import planning_mode, execution_mode
from rev.terminal.formatting import (
    create_header, create_section, create_item, create_bullet_item,
    create_tree_item, create_panel, colorize, Colors, Symbols
)
from rev.settings_manager import (
    MODE_PRESETS,
    MODE_ALIASES,
    DEFAULT_MODE_NAME,
    get_mode_config,
    get_default_mode,
    save_settings,
    reset_settings,
    get_runtime_setting,
    get_runtime_settings_snapshot,
    list_runtime_settings_by_section,
    set_runtime_setting,
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
            "Session Management": ["clear", "save", "reset", "exit"],
            "Information": ["status", "cost", "config", "doctor", "version"],
            "Model & Configuration": ["model", "mode", "set", "api-key", "private", "add-dir"],
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
        additional_dirs = session_context.get("additional_dirs", [])
        if additional_dirs:
            output.append(create_item("Additional directories", ", ".join(additional_dirs)))

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
            "View or change the AI model (supports Ollama, OpenAI, Anthropic, Gemini)"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        from rev.llm.provider_factory import detect_provider_from_model, get_provider

        if not args:
            # Show current model and available models
            output = [create_header("LLM Models", width=80)]
            output.append(create_section("Current Configuration"))

            current_provider = config.LLM_PROVIDER
            detected_provider = detect_provider_from_model(config.OLLAMA_MODEL)

            output.append(create_item("Active Model", colorize(config.OLLAMA_MODEL, Colors.BRIGHT_CYAN, bold=True)))
            output.append(create_item("Provider", f"{current_provider} (detected: {detected_provider})"))

            # Show Ollama models
            output.append(create_section("Ollama Models (Local)"))
            import requests
            try:
                response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    if models:
                        models_sorted = sorted(models, key=lambda x: x['name'])
                        for model in models_sorted:
                            model_name = model['name']
                            is_current = model_name == config.OLLAMA_MODEL

                            size_bytes = model.get('size', 0)
                            size_str = f"{size_bytes / 1_000_000_000:.1f}GB" if size_bytes > 1_000_000_000 else f"{size_bytes / 1_000_000:.0f}MB"

                            if is_current:
                                marker = colorize(f"{Symbols.ARROW} ", Colors.BRIGHT_GREEN)
                                name_colored = colorize(model_name, Colors.BRIGHT_CYAN, bold=True)
                            else:
                                marker = "  "
                                name_colored = model_name

                            output.append(f"  {marker}{name_colored:<45} {colorize(size_str, Colors.BRIGHT_BLACK)}")
                    else:
                        output.append(create_bullet_item("No models found", 'warning'))
                        output.append(f"  {colorize('Pull a model with: ollama pull <model_name>', Colors.DIM)}")
                else:
                    output.append(create_bullet_item(f"Failed to fetch models (HTTP {response.status_code})", 'cross'))
            except Exception as e:
                output.append(create_bullet_item(f"Error connecting to Ollama: {str(e)[:50]}", 'cross'))

            # Show commercial provider models - only if API keys are configured
            from rev.secrets_manager import get_api_key

            # Check which API keys are set
            openai_api_key = get_api_key("openai")
            anthropic_api_key = get_api_key("anthropic")
            gemini_api_key = get_api_key("gemini")

            has_commercial_providers = openai_api_key or anthropic_api_key or gemini_api_key

            if has_commercial_providers:
                output.append(create_section("Commercial Providers"))

            # OpenAI - only show if API key is set
            if openai_api_key:
                output.append(f"\n  {colorize('OpenAI (ChatGPT):', Colors.BRIGHT_WHITE, bold=True)}")
                openai_models = ["gpt-4-turbo-preview", "gpt-4", "gpt-3.5-turbo", "gpt-3.5-turbo-16k"]
                for model in openai_models:
                    is_current = model == config.OLLAMA_MODEL
                    marker = colorize(f"{Symbols.ARROW} ", Colors.BRIGHT_GREEN) if is_current else "    "
                    name_colored = colorize(model, Colors.BRIGHT_CYAN, bold=True) if is_current else model
                    output.append(f"  {marker}{name_colored}")

            # Anthropic - only show if API key is set
            if anthropic_api_key:
                output.append(f"\n  {colorize('Anthropic (Claude):', Colors.BRIGHT_WHITE, bold=True)}")
                anthropic_models = ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229", "claude-3-sonnet-20240229"]
                for model in anthropic_models:
                    is_current = model == config.OLLAMA_MODEL
                    marker = colorize(f"{Symbols.ARROW} ", Colors.BRIGHT_GREEN) if is_current else "    "
                    name_colored = colorize(model, Colors.BRIGHT_CYAN, bold=True) if is_current else model
                    output.append(f"  {marker}{name_colored}")

            # Gemini - only show if API key is set, dynamically fetch models
            if gemini_api_key:
                output.append(f"\n  {colorize('Google Gemini:', Colors.BRIGHT_WHITE, bold=True)}")
                try:
                    # Dynamically fetch available Gemini models (silent mode to avoid debug prints)
                    from rev.llm.providers.gemini_provider import GeminiProvider
                    provider = GeminiProvider(api_key=gemini_api_key, silent=True)
                    gemini_models = provider.get_model_list()

                    if gemini_models:
                        for model in gemini_models:
                            is_current = model == config.OLLAMA_MODEL
                            marker = colorize(f"{Symbols.ARROW} ", Colors.BRIGHT_GREEN) if is_current else "    "
                            name_colored = colorize(model, Colors.BRIGHT_CYAN, bold=True) if is_current else model
                            output.append(f"  {marker}{name_colored}")
                    else:
                        output.append(f"    {colorize('No models available', Colors.DIM)}")
                except Exception as e:
                    # Fallback to default list if API call fails
                    output.append(f"    {colorize(f'Unable to fetch models: {str(e)[:50]}', Colors.BRIGHT_BLACK)}")
                    fallback_models = ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"]
                    for model in fallback_models:
                        is_current = model == config.OLLAMA_MODEL
                        marker = colorize(f"{Symbols.ARROW} ", Colors.BRIGHT_GREEN) if is_current else "    "
                        name_colored = colorize(model, Colors.BRIGHT_CYAN, bold=True) if is_current else model
                        output.append(f"  {marker}{name_colored}")

            output.append(f"\n  {colorize('Usage: /model <model_name>', Colors.DIM)}")
            output.append(f"  {colorize('Provider auto-detected from model name', Colors.DIM)}")
            output.append(f"  {colorize('Set API keys with: /api-key set <provider>', Colors.DIM)}")
            return "\n".join(output)

        # Change model
        new_model = args[0]
        old_model = config.OLLAMA_MODEL
        config.set_model(new_model)

        # Detect provider
        provider = detect_provider_from_model(new_model)

        output = [f"\n{colorize('Model changed:', Colors.BRIGHT_WHITE, bold=True)} {old_model} {colorize(Symbols.ARROW, Colors.BRIGHT_GREEN)} {colorize(new_model, Colors.BRIGHT_CYAN, bold=True)}"]
        output.append(f"  {colorize(f'Provider: {provider}', Colors.DIM)}")

        # Check if API key is set for commercial providers
        if provider != "ollama":
            from rev.secrets_manager import get_api_key
            api_key = get_api_key(provider)
            if not api_key:
                output.append(f"  {colorize('⚠  No API key set for ' + provider, Colors.BRIGHT_YELLOW)}")
                output.append(f"  {colorize(f'Set with: /api-key set {provider}', Colors.DIM)}")

        return "\n".join(output)


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
        output.append(f"\nLLM Generation Parameters:")
        output.append(f"  Temperature:       {config.OLLAMA_TEMPERATURE}")
        output.append(f"  Context window:    {config.OLLAMA_NUM_CTX:,} tokens")
        output.append(f"  Top-p:             {config.OLLAMA_TOP_P}")
        output.append(f"  Top-k:             {config.OLLAMA_TOP_K}")
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


class SetCommand(CommandHandler):
    """View or modify runtime configuration settings."""

    def __init__(self):
        super().__init__(
            "set",
            "View or change runtime settings (e.g., /set log_retention 10)"
        )

    def _render_settings(self) -> str:
        output = [create_header("Runtime Settings", width=80)]

        for section, settings in list_runtime_settings_by_section().items():
            output.append(create_section(section))
            for setting in settings:
                try:
                    value = setting.getter()
                except Exception as exc:
                    value = f"(error: {exc})"
                output.append(
                    create_item(
                        setting.key,
                        f"{value}  - {setting.description}"
                    )
                )

        output.append(
            f"\n  {colorize('Use /set <key> <value> to update. Run /save to persist.', Colors.DIM)}"
        )

        return "\n".join(output)

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        if not args:
            return self._render_settings()

        key = args[0].lower()
        setting = get_runtime_setting(key)
        available_keys = sorted(get_runtime_settings_snapshot().keys())

        if not setting:
            available_display = ", ".join(available_keys)
            return (
                create_bullet_item(f"Unknown setting: {key}", 'cross')
                + f"\n  Available: {available_display}"
            )

        if len(args) == 1:
            output = [create_header(f"Setting: {setting.key}", width=80)]
            output.append(create_item("Current value", str(setting.getter())))
            output.append(create_item("Description", setting.description))
            output.append(
                f"\n  {colorize('Usage: /set <key> <value>', Colors.DIM)}"
            )
            return "\n".join(output)

        raw_value = " ".join(args[1:]).strip()
        if raw_value == "":
            return create_bullet_item("Please provide a value to set", 'warning')

        try:
            new_value = set_runtime_setting(key, raw_value)
        except ValueError as exc:
            return create_bullet_item(f"Invalid value for {key}: {exc}", 'cross')

        output = [create_header("Setting Updated", width=80)]
        output.append(create_bullet_item(f"{setting.key} → {new_value}", 'check'))
        output.append(create_item("Description", setting.description))
        output.append(
            f"\n  {colorize('Run /save to persist this value for future sessions', Colors.DIM)}"
        )

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


class SaveCommand(CommandHandler):
    """Persist the current session settings to disk."""

    def __init__(self):
        super().__init__(
            "save",
            "Save model, mode, and privacy settings for future sessions"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        saved_path = save_settings(session_context)

        output = [create_header("Settings Saved", width=80)]
        output.append(create_bullet_item(f"Model: {config.OLLAMA_MODEL}", 'check'))
        output.append(create_bullet_item(f"Ollama URL: {config.OLLAMA_BASE_URL}", 'check'))
        output.append(create_bullet_item(f"Mode: {session_context.get('execution_mode', DEFAULT_MODE_NAME)}", 'check'))
        privacy_status = "Enabled" if config.get_private_mode() else "Disabled"
        output.append(create_bullet_item(f"Private mode: {privacy_status}", 'check'))
        runtime_settings = get_runtime_settings_snapshot()
        if runtime_settings:
            output.append(create_section("Runtime Settings"))
            for key, value in runtime_settings.items():
                output.append(create_item(key, str(value)))
        output.append(f"\n  {colorize('Saved to', Colors.DIM)} {saved_path}")
        output.append(f"  {colorize('Settings will auto-load next time you start rev', Colors.DIM)}")

        return "\n".join(output)


class ResetCommand(CommandHandler):
    """Reset configuration to defaults and clear saved settings."""

    def __init__(self):
        super().__init__(
            "reset",
            "Reset model, mode, and privacy settings to defaults"
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        reset_settings(session_context)
        default_mode, _ = get_default_mode()

        output = [create_header("Settings Reset", width=80)]
        output.append(create_bullet_item(f"Model reset to {config.OLLAMA_MODEL}", 'check'))
        output.append(create_bullet_item(f"Ollama URL reset to {config.OLLAMA_BASE_URL}", 'check'))
        output.append(create_bullet_item(f"Mode reset to {default_mode}", 'check'))
        privacy_status = "Enabled" if config.get_private_mode() else "Disabled"
        output.append(create_bullet_item(f"Private mode: {privacy_status}", 'check'))
        output.append(f"\n  {colorize('Saved settings cleared; defaults restored', Colors.DIM)}")

        return "\n".join(output)


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


class HistoryCommand(CommandHandler):
    """Show command history."""

    def __init__(self):
        super().__init__(
            "history",
            "Show command and input history",
            aliases=["h"]
        )

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        from rev.terminal.history import get_history

        history = get_history()
        output = [create_header("Command History", width=80)]

        cmd_history = history.get_command_history()
        input_history = history.get_input_history()

        if cmd_history:
            output.append(create_section("Commands"))
            for i, cmd in enumerate(cmd_history, 1):
                output.append(f"  {i:3}. {cmd}")

        if input_history:
            output.append(create_section("Inputs"))
            for i, inp in enumerate(input_history, 1):
                output.append(f"  {i:3}. {inp[:80]}{'...' if len(inp) > 80 else ''}")

        if not cmd_history and not input_history:
            output.append("  No history yet")

        return "\n".join(output)


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
            test_file = config.TEST_MARKER_FILE
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
        tracked_dirs = session_context.setdefault("additional_dirs", [])
        for dir_path in args:
            path = Path(dir_path).expanduser().resolve()
            if path.exists() and path.is_dir():
                path_str = str(path)
                if path_str not in tracked_dirs:
                    tracked_dirs.append(path_str)
                try:
                    config.register_additional_root(path)
                except ValueError as exc:
                    return f"Error: {exc}"
                added_dirs.append(path_str)
            else:
                return f"Error: Directory not found: {dir_path}"

        if added_dirs:
            return f"Added directories: {', '.join(added_dirs)}"

        return "No new directories added (already tracked)"


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
        return build_version_output(config.OLLAMA_MODEL, system_info)


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
        output.append("  Shell commands:    Allowed (securely validated)")
        output.append("  SSH operations:    " + ("Allowed" if config.SSH_AVAILABLE else "Not available"))
        output.append("\n(Fine-grained permission controls via tool_policy.yaml)")

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


class PrivateCommand(CommandHandler):
    """Toggle private mode to disable public MCP servers."""

    def __init__(self):
        super().__init__(
            "private",
            "Toggle private mode to disable all public MCP servers"
        )

    def get_help(self) -> str:
        return """Toggle private mode to disable all public MCP servers.

Private mode is useful when working with secure or unsharable code.
When enabled, all public MCP servers are disabled, but private servers
with API keys (like GitHub with your token) remain enabled.

Usage:
  /private on     - Enable private mode
  /private off    - Disable private mode
  /private        - Show current status

Public MCP servers disabled in private mode:
  - memory, sequential-thinking, fetch (core servers)
  - deepwiki, exa-search (code search)
  - semgrep (static analysis)
  - cloudflare-docs, astro-docs (documentation)
  - huggingface (AI models)

Private servers (with API keys) remain enabled:
  - brave-search (if BRAVE_API_KEY is set)
  - github (if GITHUB_TOKEN is set)
"""

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        if not args:
            # Show current status
            current_status = config.get_private_mode()
            output = [create_header("Private Mode Status", width=80)]
            status_text = "ENABLED" if current_status else "DISABLED"
            status_color = Colors.BRIGHT_RED if current_status else Colors.BRIGHT_GREEN
            output.append(f"\n  {colorize('Private Mode:', Colors.BRIGHT_WHITE)} {colorize(status_text, status_color, bold=True)}\n")

            if current_status:
                output.append(create_section("Current Configuration"))
                output.append(create_bullet_item("Public MCP servers are disabled", 'cross'))
                output.append(create_bullet_item("Private MCP servers (with API keys) remain enabled", 'check'))
                output.append(f"\n  {colorize('Your code and data will not be sent to public MCP servers', Colors.BRIGHT_GREEN)}")
            else:
                output.append(create_section("Current Configuration"))
                output.append(create_bullet_item("All MCP servers are available", 'check'))
                output.append(f"\n  {colorize('Use /private on to disable public servers for secure code', Colors.DIM)}")

            output.append(f"\n  {colorize('Type /private on or /private off to change', Colors.DIM)}")
            return "\n".join(output)

        action = args[0].lower()

        if action == "on":
            config.set_private_mode(True)
            os.environ["REV_PRIVATE_MODE"] = "true"

            # Reload MCP client with new settings
            from rev.mcp.client import mcp_client
            mcp_client.servers.clear()
            mcp_client._load_default_servers()

            output = [create_header("Private Mode Enabled", width=80)]
            output.append(f"\n  {colorize('✓ Private mode is now enabled', Colors.BRIGHT_GREEN)}\n")
            output.append(create_section("Changes Applied"))
            output.append(create_bullet_item("All public MCP servers have been disabled", 'check'))
            output.append(create_bullet_item("Private servers (with API keys) remain active", 'check'))
            output.append(create_bullet_item("Your code will not be sent to public servers", 'check'))
            output.append(f"\n  {colorize('Use /private off to re-enable public servers', Colors.DIM)}")
            return "\n".join(output)

        elif action == "off":
            config.set_private_mode(False)
            os.environ["REV_PRIVATE_MODE"] = "false"

            # Reload MCP client with new settings
            from rev.mcp.client import mcp_client
            mcp_client.servers.clear()
            mcp_client._load_default_servers()

            output = [create_header("Private Mode Disabled", width=80)]
            output.append(f"\n  {colorize('✓ Private mode is now disabled', Colors.BRIGHT_GREEN)}\n")
            output.append(create_section("Changes Applied"))
            output.append(create_bullet_item("All MCP servers are now available", 'check'))
            output.append(f"\n  {colorize('Use /private on to disable public servers', Colors.DIM)}")
            return "\n".join(output)

        else:
            return f"\n{colorize('Invalid argument:', Colors.BRIGHT_RED)} {action}\n{self.get_help()}"


class ModeCommand(CommandHandler):
    """Set execution mode with predefined configurations."""

    def __init__(self):
        super().__init__(
            "mode",
            "Set execution mode: simple, advanced, or deep"
        )

    def get_help(self) -> str:
        return """Set the execution mode with predefined configurations.

Available modes:

  simple      - Fast execution with minimal overhead
                • No research or learning
                • Lenient review
                • Shallow codebase exploration
                • Sequential execution

  advanced    - Balanced approach (default)
                • Medium research depth
                • Moderate review strictness
                • Validation enabled
                • Sequential execution (single worker)

  deep        - Comprehensive analysis and validation
                • Deep research + learning
                • Strict review + action review
                • Full validation with auto-fix
                • Sequential execution (single worker)

Aliases:
  standard -> advanced
  thorough -> deep
  max -> deep

Usage: /mode <mode_name>
Example: /mode advanced
"""

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        if not args:
            # Show current mode
            current_mode = session_context.get("execution_mode", DEFAULT_MODE_NAME)
            output = [create_header("Current Execution Mode", width=80)]
            output.append(f"\n  {colorize(Symbols.ARROW, Colors.BRIGHT_GREEN)} {colorize(current_mode, Colors.BRIGHT_CYAN, bold=True)}")
            output.append(f"\n{self.get_help()}")
            return "\n".join(output)

        mode = args[0].lower()

        if mode not in MODE_PRESETS and mode not in MODE_ALIASES:
            return f"\n{colorize('Unknown mode:', Colors.BRIGHT_RED)} {mode}\n{self.get_help()}"

        normalized_mode, mode_config = get_mode_config(mode)

        # Apply mode configuration
        session_context["execution_mode"] = normalized_mode
        session_context["mode_config"] = mode_config

        # Build output
        output = [create_header(f"Mode: {normalized_mode}", width=80)]
        output.append(f"\n  {colorize(mode_config['description'], Colors.BRIGHT_WHITE)}\n")
        output.append(create_section("Configuration Applied"))

        if mode_config["orchestrate"]:
            output.append(create_bullet_item("Orchestrator mode enabled", 'check'))

        output.append(create_item("Research", f"{'Enabled' if mode_config['research'] else 'Disabled'} ({mode_config['research_depth']})"))
        output.append(create_item("Learning", 'Enabled' if mode_config['learn'] else 'Disabled'))
        output.append(create_item("Review", f"{'Enabled' if mode_config['review'] else 'Disabled'} ({mode_config['review_strictness']})"))
        output.append(create_item("Validation", f"{'Enabled' if mode_config['validate'] else 'Disabled'}{' + auto-fix' if mode_config['auto_fix'] else ''}"))
        output.append(create_item("Action Review", 'Enabled' if mode_config['action_review'] else 'Disabled'))
        output.append(create_item("Parallel Workers", str(mode_config['parallel'])))

        output.append(f"\n  {colorize('✓ Mode configuration saved to session', Colors.BRIGHT_GREEN)}")
        output.append(f"  {colorize('Next task will use these settings', Colors.DIM)}")

        return "\n".join(output)


class ApiKeyCommand(CommandHandler):
    """Manage API keys for commercial LLM providers."""

    def __init__(self):
        super().__init__(
            "api-key",
            "Manage API keys for commercial LLM providers (OpenAI, Anthropic, Gemini)",
            aliases=["apikey", "keys"]
        )

    def get_help(self) -> str:
        return f"""
{self.description}

Commands:
  /api-key list              - Show all saved API keys (masked)
  /api-key set <provider>    - Set API key for a provider (interactive)
  /api-key delete <provider> - Delete API key for a provider

Providers: openai, anthropic, gemini

Examples:
  /api-key list
  /api-key set openai
  /api-key delete anthropic

Note: API keys are stored securely in .rev/secrets.json with restricted permissions.
You can also use: /set openai_api_key <key> to set keys directly.
"""

    def execute(self, args: List[str], session_context: Dict[str, Any]) -> str:
        from rev.secrets_manager import get_api_key, set_api_key, delete_api_key, mask_api_key

        if not args:
            # Show help
            return self.get_help()

        action = args[0].lower()

        # List keys
        if action == "list":
            output = [create_header("Saved API Keys", width=80)]
            output.append(create_section("Commercial LLM Providers"))

            for provider in ["openai", "anthropic", "gemini"]:
                api_key = get_api_key(provider)
                masked = mask_api_key(api_key) if api_key else colorize("(not set)", Colors.DIM)
                output.append(create_item(provider.capitalize(), masked))

            output.append(f"\n  {colorize('Keys stored in .rev/secrets.json', Colors.DIM)}")
            output.append(f"  {colorize('Use /api-key set <provider> to add keys', Colors.DIM)}")

            return "\n".join(output)

        # Set key
        elif action == "set":
            if len(args) < 2:
                return create_bullet_item("Error: Missing provider name", 'cross') + "\n  Usage: /api-key set <provider>"

            provider = args[1].lower()
            if provider not in ["openai", "anthropic", "gemini"]:
                return create_bullet_item(f"Error: Invalid provider '{provider}'", 'cross') + "\n  Valid providers: openai, anthropic, gemini"

            # Get API key from user (without echoing)
            import getpass
            print(f"\nEnter {provider.capitalize()} API key (input hidden):")
            try:
                api_key = getpass.getpass("API Key: ").strip()
            except (KeyboardInterrupt, EOFError):
                return "\n" + create_bullet_item("Cancelled", 'cross')

            if not api_key:
                return create_bullet_item("Error: API key cannot be empty", 'cross')

            # Save the key
            set_api_key(provider, api_key)

            output = [create_header(f"{provider.capitalize()} API Key", width=80)]
            output.append(create_bullet_item(f"Successfully saved {provider} API key", 'check'))
            output.append(create_item("Key", mask_api_key(api_key)))
            output.append(f"\n  {colorize('✓ Key stored securely in .rev/secrets.json', Colors.BRIGHT_GREEN)}")
            output.append(f"  {colorize(f'Use /set llm_provider {provider} to activate', Colors.DIM)}")

            return "\n".join(output)

        # Delete key
        elif action == "delete":
            if len(args) < 2:
                return create_bullet_item("Error: Missing provider name", 'cross') + "\n  Usage: /api-key delete <provider>"

            provider = args[1].lower()
            if provider not in ["openai", "anthropic", "gemini"]:
                return create_bullet_item(f"Error: Invalid provider '{provider}'", 'cross') + "\n  Valid providers: openai, anthropic, gemini"

            if delete_api_key(provider):
                return create_bullet_item(f"Deleted {provider} API key", 'check')
            else:
                return create_bullet_item(f"No API key found for {provider}", 'info')

        else:
            return create_bullet_item(f"Unknown action: {action}", 'cross') + "\n" + self.get_help()


# Command registry - dictionary for O(1) lookup
def _build_command_registry() -> Dict[str, CommandHandler]:
    """Build the command registry with all available commands."""
    handlers = [
        HelpCommand(),
        StatusCommand(),
        CostCommand(),
        ModelCommand(),
        ConfigCommand(),
        SetCommand(),
        ClearCommand(),
        SaveCommand(),
        ResetCommand(),
        ExitCommand(),
        HistoryCommand(),
        DoctorCommand(),
        AddDirCommand(),
        InitCommand(),
        ReviewCommand(),
        ValidateCommand(),
        ExportCommand(),
        VersionCommand(),
        CompactCommand(),
        PermissionsCommand(),
        AgentsCommand(),
        ModeCommand(),
        PrivateCommand(),
        ApiKeyCommand()
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
