#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Centralized debug logging system for rev CLI.

This module provides comprehensive debug logging capabilities that can be enabled
with the --debug flag. Logs are written to a file in a format optimized for LLM
review and debugging.
"""

import os
import sys
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from functools import wraps

from rev import config


def prune_old_logs(log_dir: Path, keep: int) -> None:
    """Remove old log files beyond the configured retention limit."""

    if keep < 1 or not log_dir.exists():
        return

    log_files = sorted(
        [path for path in log_dir.glob("*.log") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for stale_file in log_files[keep:]:
        try:
            stale_file.unlink()
        except Exception:
            # Best-effort cleanup; ignore failures to avoid interrupting the session
            continue


class DebugLogger:
    """Centralized debug logger with component-specific logging."""

    _instance: Optional['DebugLogger'] = None
    _enabled: bool = False
    _log_file: Optional[Path] = None
    _loggers: Dict[str, logging.Logger] = {}

    def __init__(self, enabled: bool = False, log_dir: Optional[Path] = None):
        """Initialize the debug logger.

        Args:
            enabled: Whether debug logging is enabled
            log_dir: Directory to store log files (defaults to .rev/logs/)
        """
        self._enabled = enabled
        self._trace_context: Dict[str, Any] = {}

        if enabled:
            # Create log directory
            if log_dir is None:
                log_dir = config.LOGS_DIR
            log_dir.mkdir(exist_ok=True, parents=True)

            # Create log file with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_file = log_dir / f"rev_debug_{timestamp}.log"

            # Set up root logger
            self._setup_logging()

            prune_old_logs(log_dir, config.LOG_RETENTION_LIMIT)

            # Log session start
            self.log("system", "DEBUG_SESSION_START", {
                "timestamp": datetime.now().isoformat(),
                "log_file": str(self._log_file),
                "cwd": str(Path.cwd())
            })

    @classmethod
    def initialize(cls, enabled: bool = False, log_dir: Optional[Path] = None) -> 'DebugLogger':
        """Initialize the global debug logger instance.

        Args:
            enabled: Whether debug logging is enabled
            log_dir: Directory to store log files

        Returns:
            The DebugLogger instance
        """
        if cls._instance is None:
            cls._instance = cls(enabled, log_dir)
        
        if getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False):
            path_val = getattr(config, "LLM_TRANSACTION_LOG_PATH", "")
            if path_val:
                log_path = Path(path_val)
                if log_path.exists():
                    last_log_path = log_path.with_suffix(log_path.suffix + '.last')
                    if last_log_path.exists():
                        last_log_path.unlink()
                    log_path.rename(last_log_path)
                    
        return cls._instance

    @classmethod
    def get_instance(cls) -> 'DebugLogger':
        """Get the global debug logger instance."""
        if cls._instance is None:
            cls._instance = cls(enabled=False)
        return cls._instance

    def set_trace_context(self, updates: Dict[str, Any], *, replace: bool = False) -> None:
        """Attach contextual metadata to subsequent LLM/transaction logs."""
        if not isinstance(updates, dict):
            return
        if replace:
            self._trace_context = {}
        for key, value in updates.items():
            if value is None:
                self._trace_context.pop(key, None)
            else:
                self._trace_context[key] = value

    def get_trace_context(self) -> Dict[str, Any]:
        """Return a copy of the current trace context."""
        return dict(self._trace_context)

    def _setup_logging(self):
        """Set up the logging configuration."""
        # Create formatter for detailed logs
        formatter = logging.Formatter(
            '%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Create file handler
        file_handler = logging.FileHandler(self._log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        # Configure root logger
        root_logger = logging.getLogger('rev')
        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.propagate = False

    def get_logger(self, component: str) -> logging.Logger:
        """Get or create a logger for a specific component.

        Args:
            component: Component name (e.g., 'main', 'llm', 'executor')

        Returns:
            Logger instance for the component
        """
        if component not in self._loggers:
            self._loggers[component] = logging.getLogger(f'rev.{component}')
        return self._loggers[component]

    def log(self, component: str, event: str, data: Optional[Dict[str, Any]] = None, level: str = "INFO"):
        """Log a structured event.

        Args:
            component: Component name (e.g., 'main', 'llm', 'executor')
            event: Event type/name
            data: Optional dictionary of event data
            level: Log level (DEBUG, INFO, WARNING, ERROR)
        """
        if not self._enabled:
            return

        logger = self.get_logger(component)

        # Format the log message
        message = f"[{event}]"
        if data:
            # Pretty print the data for LLM readability
            message += f" {json.dumps(data, indent=2, default=str)}"

        # Log at the appropriate level
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, message)

    def log_function_call(self, component: str, function_name: str, args: tuple = (), kwargs: dict = None):
        """Log a function call with its arguments.

        Args:
            component: Component name
            function_name: Name of the function being called
            args: Positional arguments
            kwargs: Keyword arguments
        """
        if not self._enabled:
            return

        data = {
            "function": function_name,
            "args": [str(arg)[:200] for arg in args],  # Truncate long args
        }
        if kwargs:
            data["kwargs"] = {k: str(v)[:200] for k, v in kwargs.items()}

        self.log(component, "FUNCTION_CALL", data, "DEBUG")

    def log_llm_request(self, model: str, messages: list, tools: Optional[list] = None):
        """Log an LLM API request.

        Args:
            model: Model name
            messages: List of messages
            tools: Optional list of tools
        """
        if not self._enabled:
            return

        data = {
            "model": model,
            "message_count": len(messages),
            "messages": [
                {
                    "role": msg.get("role"),
                    "content": str(msg.get("content", ""))[:500]  # Truncate long content
                }
                for msg in messages
            ],
        }
        if tools:
            data["tools_count"] = len(tools)
            data["tools"] = [tool.get("name") for tool in tools]

        self.log("llm", "LLM_REQUEST", data, "DEBUG")

    def log_llm_response(self, model: str, response: dict, cached: bool = False):
        """Log an LLM API response.

        Args:
            model: Model name
            response: Response dictionary
            cached: Whether this was a cached response
        """
        if not self._enabled:
            return

        data = {
            "model": model,
            "cached": cached,
            "response_type": type(response).__name__,
        }

        # Extract relevant response info
        if isinstance(response, dict):
            if "message" in response:
                msg = response["message"]
                data["role"] = msg.get("role")
                data["content_preview"] = str(msg.get("content", ""))[:500]
                if "tool_calls" in msg:
                    data["tool_calls"] = [
                        {
                            "name": tc.get("function", {}).get("name"),
                            "args_preview": str(tc.get("function", {}).get("arguments", ""))[:200]
                        }
                        for tc in msg.get("tool_calls", [])
                    ]

        self.log("llm", "LLM_RESPONSE", data, "DEBUG")

    def log_llm_transcript(self, *, model: str, messages: Any, response: Any, tools: Any = None):
        """Persist full LLM request/response (no truncation) when tracing is enabled.

        Includes additional system state for easier debugging.
        Also writes a summary to the run log for unified review.
        """
        if not getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False):
            return
        try:
            # Write summary to run log first (for unified review)
            from rev.run_log import write_run_log_line
            timestamp = datetime.utcnow().isoformat()

            # Extract summary info
            msg_count = len(messages) if isinstance(messages, list) else 0
            last_msg = messages[-1] if isinstance(messages, list) and messages else {}
            last_role = last_msg.get("role", "?") if isinstance(last_msg, dict) else "?"
            last_content_preview = str(last_msg.get("content", ""))[:100] if isinstance(last_msg, dict) else ""

            has_response = response and not (isinstance(response, dict) and response.get("pending"))
            response_preview = ""
            if has_response:
                if isinstance(response, dict):
                    resp_msg = response.get("message", {})
                    if isinstance(resp_msg, dict):
                        response_preview = str(resp_msg.get("content", ""))[:100]

            write_run_log_line("\n" + "=" * 80)
            write_run_log_line(f"LLM TRANSCRIPT [{timestamp}Z]")
            write_run_log_line("=" * 80)
            write_run_log_line(f"Model: {model}")
            write_run_log_line(f"Messages: {msg_count} (last: {last_role})")
            if last_content_preview:
                write_run_log_line(f"Last message preview: {last_content_preview}...")
            if has_response and response_preview:
                write_run_log_line(f"Response preview: {response_preview}...")
            elif not has_response:
                write_run_log_line("Response: <pending>")
            write_run_log_line("=" * 80 + "\n")
            # Gather extra context for debugging
            extra_context = {
                "cwd": os.getcwd(),
                "platform": sys.platform,
                "python_version": sys.version,
            }
            
            # Filtered environment variables (no secrets)
            try:
                secret_keywords = {'key', 'token', 'secret', 'password', 'auth', 'credential', 'cert'}
                extra_context["env"] = {
                    k: v for k, v in os.environ.items() 
                    if not any(kw in k.lower() for kw in secret_keywords)
                }
            except Exception:
                pass
            
            # Simple file listing of root
            try:
                extra_context["files_root"] = os.listdir(".")[:50]
            except Exception:
                pass
                
            # Available tools
            try:
                from rev.tools.registry import get_available_tools
                extra_context["available_tools"] = [t.get("function", {}).get("name") for t in get_available_tools() if isinstance(t, dict)]
            except Exception:
                pass
                
            # Git status (to see actual file changes)
            try:
                import subprocess
                extra_context["git_status"] = subprocess.check_output(["git", "status", "--short"], timeout=5).decode("utf-8")
            except Exception:
                pass

            payload = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "response": response,
                "system_state": extra_context,
                "trace_context": self.get_trace_context(),
                "tools_enabled": bool(tools),
                "message_count": msg_count,
                "last_message_role": last_role,
            }
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            path_val = getattr(config, "LLM_TRANSACTION_LOG_PATH", "")
            if not path_val:
                return
            path = Path(path_val)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(f"==== LLM TRANSCRIPT {datetime.utcnow().isoformat()}Z ====\n")
                f.write(content)
                f.write("\n\n")
                f.flush()
        except Exception:
            # Best-effort tracing; never crash caller
            pass

    def log_transaction_event(self, event_type: str, data: Dict[str, Any]):
        """Log a non-LLM event (like a tool result or orchestrator decision) to the transaction log.

        Also writes a summary to the run log for unified review.
        """
        if not getattr(config, "LLM_TRANSACTION_LOG_ENABLED", False):
            return
        try:
            # Write summary to run log first (for unified review)
            from rev.run_log import write_run_log_line
            timestamp = datetime.utcnow().isoformat() + "Z"

            # For orchestrator decisions, include action details
            if event_type == "ORCHESTRATOR_DECISION":
                action_type = data.get("action_type", "?")
                description = data.get("description", "")[:100]
                write_run_log_line(f"[ORCHESTRATOR] {action_type.upper()}: {description}...")

            payload = {
                "event_type": event_type,
                "timestamp": timestamp,
                "data": data,
                "trace_context": self.get_trace_context()
            }
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            path_val = getattr(config, "LLM_TRANSACTION_LOG_PATH", "")
            if not path_val:
                return
            path = Path(path_val)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(f"==== TRANSACTION EVENT {event_type} ====\n")
                f.write(content)
                f.write("\n\n")
                f.flush()
        except Exception:
            pass

    def log_tool_execution(self, tool_name: str, arguments: dict, result: Any = None, error: Optional[str] = None, duration_ms: float = 0.0):
        """Log a tool execution.

        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            result: Tool execution result
            error: Error message if execution failed
            duration_ms: How long the tool took to run
        """
        if not self._enabled:
            return

        data = {
            "tool": tool_name,
            "arguments": {k: str(v)[:200] for k, v in arguments.items()},
            "duration_ms": round(duration_ms, 2)
        }

        if error:
            data["error"] = str(error)
            level = "ERROR"
        else:
            data["result_type"] = type(result).__name__
            data["result_preview"] = str(result)[:500] if result is not None else None
            level = "DEBUG"

        self.log("tools", "TOOL_EXECUTION", data, level)

    def log_task_status(self, task_id: str, status: str, details: Optional[Dict[str, Any]] = None):
        """Log a task status change.

        Args:
            task_id: Task identifier
            status: New status
            details: Optional additional details
        """
        if not self._enabled:
            return

        data = {
            "task_id": task_id,
            "status": status,
        }
        if details:
            data["details"] = details

        self.log("executor", "TASK_STATUS_CHANGE", data, "INFO")

    def log_error(self, component: str, error: Exception, context: Optional[Dict[str, Any]] = None):
        """Log an error with context.

        Args:
            component: Component where error occurred
            error: The exception
            context: Optional context information
        """
        if not self._enabled:
            return

        data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        if context:
            data["context"] = context

        self.log(component, "ERROR", data, "ERROR")

    def log_workflow_phase(self, phase: str, details: Optional[Dict[str, Any]] = None):
        """Log a workflow phase transition.

        Args:
            phase: Phase name (e.g., 'planning', 'review', 'execution', 'validation')
            details: Optional phase details
        """
        if not self._enabled:
            return

        data = {"phase": phase}
        if details:
            data.update(details)

        self.log("main", "WORKFLOW_PHASE", data, "INFO")

    def _log_plain(self, level: str, msg: str, *args: Any, **kwargs: Any) -> None:
        """Support standard logging-style calls (info/warning/error/debug).

        Some parts of the codebase expect a logger compatible with the standard
        :mod:`logging` interface. These helpers forward those calls into the
        structured logger when debug logging is enabled, and safely no-op
        otherwise.

        Args:
            level: Log level name (e.g., "INFO", "ERROR").
            msg: Message format string.
            *args: Positional format arguments.
            **kwargs: Keyword format arguments.
        """
        if not self._enabled:
            return

        logger = self.get_logger("general")
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an informational message when debug logging is enabled."""
        self._log_plain("INFO", msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a warning message when debug logging is enabled."""
        self._log_plain("WARNING", msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an error message when debug logging is enabled."""
        self._log_plain("ERROR", msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a debug message when debug logging is enabled."""
        self._log_plain("DEBUG", msg, *args, **kwargs)

    @property
    def enabled(self) -> bool:
        """Check if debug logging is enabled."""
        return self._enabled

    @property
    def log_file_path(self) -> Optional[Path]:
        """Get the path to the current log file."""
        return self._log_file

    def close(self):
        """Close the logger and write session end marker."""
        if self._enabled:
            self.log("system", "DEBUG_SESSION_END", {
                "timestamp": datetime.now().isoformat()
            })

            # Close all handlers
            for logger in self._loggers.values():
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)

            root_logger = logging.getLogger('rev')
            for handler in root_logger.handlers[:]:
                handler.close()
                root_logger.removeHandler(handler)


def log_function(component: str):
    """Decorator to automatically log function calls.

    Args:
        component: Component name for logging

    Usage:
        @log_function('executor')
        def execute_task(task):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = DebugLogger.get_instance()
            if logger.enabled:
                logger.log_function_call(component, func.__name__, args, kwargs)
            return func(*args, **kwargs)
        return wrapper
    return decorator


# Convenience functions for global logger access
def get_logger() -> DebugLogger:
    """Get the global debug logger instance."""
    return DebugLogger.get_instance()


def is_debug_enabled() -> bool:
    """Check if debug logging is enabled."""
    return get_logger().enabled
