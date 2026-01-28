#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Error Taxonomy for Tool Execution.

This module provides a standardized error classification system for all tools.
Tool errors should be structured to enable intelligent recovery and better
diagnostics.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ToolErrorType(Enum):
    """Standardized error categories for all tool execution failures.

    Each error type enables specific recovery strategies:
    - TRANSIENT: Retry with exponential backoff
    - NOT_FOUND: Research phase needed to locate missing resources
    - PERMISSION: Ask user or check workspace settings
    - SYNTAX: Generated code has errors, needs fixing
    - VALIDATION: Invalid input parameters, need to correct
    - TIMEOUT: Command took too long, may need different approach
    - NETWORK: API/network failure, retry or check connectivity
    - CONFLICT: Resource already exists or conflicting state
    - UNKNOWN: Fallback for unclassified errors
    """

    # Retryable transient errors
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    NETWORK = "network"

    # Non-retryable user/environment issues
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    SYNTAX_ERROR = "syntax_error"
    VALIDATION_ERROR = "validation_error"

    # Conflict and state issues
    CONFLICT = "conflict"

    # Fallback
    UNKNOWN = "unknown"

    @property
    def is_retryable(self) -> bool:
        """Whether this error type should trigger automatic retry."""
        return self in {
            ToolErrorType.TRANSIENT,
            ToolErrorType.TIMEOUT,
            ToolErrorType.NETWORK,
        }

    @property
    def recoverable_by_agent(self) -> bool:
        """Whether an agent can recover from this error without user help."""
        return self in {
            ToolErrorType.TRANSIENT,
            ToolErrorType.TIMEOUT,
            ToolErrorType.NETWORK,
            ToolErrorType.NOT_FOUND,
            ToolErrorType.SYNTAX_ERROR,
            ToolErrorType.VALIDATION_ERROR,
        }

    @property
    def requires_user_input(self) -> bool:
        """Whether this error requires user input to resolve."""
        return self in {
            ToolErrorType.PERMISSION_DENIED,
            ToolErrorType.CONFLICT,
        }


@dataclass
class ToolError:
    """Structured error representation for tool execution failures.

    All tools should return errors in this format (or compatible JSON)
    to enable intelligent recovery.
    """

    error_type: ToolErrorType
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True
    suggested_recovery: List[str] = field(default_factory=list)
    original_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "error": self.message,
            "error_type": self.error_type.value,
            "recoverable": self.recoverable,
            "suggested_recovery": self.suggested_recovery,
            "context": self.context,
            "original_error": self.original_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolError":
        """Create ToolError from dict (e.g., from JSON response)."""
        error_type_str = data.get("error_type", "unknown")
        try:
            error_type = ToolErrorType(error_type_str)
        except ValueError:
            error_type = ToolErrorType.UNKNOWN

        return cls(
            error_type=error_type,
            message=data.get("error", data.get("message", "Unknown error")),
            context=data.get("context", {}),
            recoverable=data.get("recoverable", True),
            suggested_recovery=data.get("suggested_recovery", []),
            original_error=data.get("original_error"),
        )

    @classmethod
    def from_exception(
        cls,
        exc: Exception,
        tool_name: str,
        *,
        custom_type: Optional[ToolErrorType] = None,
        **kwargs
    ) -> "ToolError":
        """Create ToolError from a Python exception."""
        error_type = custom_type or cls._classify_exception(exc, tool_name)
        message = f"{tool_name}: {str(exc)}"
        suggested_recovery = cls._get_suggested_recovery(error_type, tool_name, exc)

        return cls(
            error_type=error_type,
            message=message,
            context={"exception_type": type(exc).__name__, "tool": tool_name},
            recoverable=error_type.recoverable_by_agent,
            suggested_recovery=suggested_recovery,
            original_error=str(exc),
            **kwargs
        )

    @staticmethod
    def _classify_exception(exc: Exception, tool_name: str) -> ToolErrorType:
        """Classify a Python exception into a ToolErrorType."""
        exc_type = type(exc).__name__
        exc_msg = str(exc).lower()

        # File-related errors
        if "FileNotFoundError" in exc_type or "no such file" in exc_msg:
            return ToolErrorType.NOT_FOUND
        if "PermissionError" in exc_type or "permission denied" in exc_msg:
            return ToolErrorType.PERMISSION_DENIED
        if "FileExistsError" in exc_type or "already exists" in exc_msg:
            return ToolErrorType.CONFLICT

        # Network/transient errors
        if "TimeoutError" in exc_type or "timeout" in exc_msg:
            return ToolErrorType.TIMEOUT
        if "ConnectionError" in exc_type or "connection" in exc_msg:
            return ToolErrorType.NETWORK

        # Syntax/parse errors
        if "SyntaxError" in exc_type or "parse error" in exc_msg:
            return ToolErrorType.SYNTAX_ERROR

        # Validation errors
        if "ValueError" in exc_type or "KeyError" in exc_type:
            return ToolErrorType.VALIDATION_ERROR

        return ToolErrorType.UNKNOWN

    @staticmethod
    def _get_suggested_recovery(error_type: ToolErrorType, tool_name: str, exc: Exception) -> List[str]:
        """Get suggested recovery steps for an error type."""
        suggestions = []

        if error_type == ToolErrorType.NOT_FOUND:
            suggestions = [
                f"Use search_code or list_dir to locate the missing file",
                f"Check if the file path is relative to workspace root",
                f"Verify the file name spelling and extension",
            ]
        elif error_type == ToolErrorType.PERMISSION_DENIED:
            suggestions = [
                f"Check workspace permissions for the target path",
                f"Verify the file/directory is not in use",
                f"Consider using a different file path",
            ]
        elif error_type == ToolErrorType.SYNTAX_ERROR:
            suggestions = [
                f"Review the generated code for syntax issues",
                f"Use a linter to identify the specific error location",
                f"Check for unmatched brackets, quotes, or indentation",
            ]
        elif error_type == ToolErrorType.VALIDATION_ERROR:
            suggestions = [
                f"Verify the tool arguments match the expected schema",
                f"Check the tool documentation for required parameters",
                f"Ensure all required fields are provided",
            ]
        elif error_type == ToolErrorType.TIMEOUT:
            suggestions = [
                f"The operation took too long; consider breaking it into smaller steps",
                f"Check if the command is waiting for user input",
                f"Try running with a timeout parameter or different approach",
            ]
        elif error_type == ToolErrorType.NETWORK:
            suggestions = [
                f"Check network connectivity",
                f"Verify API endpoint is accessible",
                f"Retry the operation after a short delay",
            ]
        elif error_type == ToolErrorType.CONFLICT:
            suggestions = [
                f"The resource already exists or has conflicting changes",
                f"Consider using a different name or explicitly overwrite",
                f"Review the current state before proceeding",
            ]
        elif error_type == ToolErrorType.TRANSIENT:
            suggestions = [
                f"Retry the operation after a short delay",
                f"Check system resources and try again",
            ]

        return suggestions


# Error factory functions for common scenarios

def file_not_found_error(file_path: str, tool_name: str = "file_operation") -> ToolError:
    """Create a NOT_FOUND error for missing files."""
    return ToolError(
        error_type=ToolErrorType.NOT_FOUND,
        message=f"{tool_name}: File not found: {file_path}",
        context={"file_path": file_path, "tool": tool_name},
        recoverable=True,
        suggested_recovery=[
            f"Use search_code or list_dir to locate the file",
            f"Check if the file path is relative to workspace root",
        ],
    )


def permission_denied_error(path: str, tool_name: str = "file_operation") -> ToolError:
    """Create a PERMISSION_DENIED error."""
    return ToolError(
        error_type=ToolErrorType.PERMISSION_DENIED,
        message=f"{tool_name}: Permission denied: {path}",
        context={"path": path, "tool": tool_name},
        recoverable=False,
        suggested_recovery=[
            f"Check workspace permissions for {path}",
            f"Verify the file/directory is not in use",
        ],
    )


def syntax_error(error_msg: str, file_path: str = "", tool_name: str = "code_operation") -> ToolError:
    """Create a SYNTAX_ERROR for code generation issues."""
    context = {"tool": tool_name}
    if file_path:
        context["file_path"] = file_path

    return ToolError(
        error_type=ToolErrorType.SYNTAX_ERROR,
        message=f"{tool_name}: Syntax error - {error_msg}",
        context=context,
        recoverable=True,
        suggested_recovery=[
            f"Review the generated code for syntax issues",
            f"Use a linter to identify the specific error location",
        ],
    )


def timeout_error(operation: str, timeout_seconds: int = None, tool_name: str = "command") -> ToolError:
    """Create a TIMEOUT error."""
    msg = f"{tool_name}: Operation timed out - {operation}"
    if timeout_seconds:
        msg += f" (timeout: {timeout_seconds}s)"

    return ToolError(
        error_type=ToolErrorType.TIMEOUT,
        message=msg,
        context={"operation": operation, "timeout": timeout_seconds, "tool": tool_name},
        recoverable=True,
        suggested_recovery=[
            f"The operation took too long; consider breaking it into smaller steps",
            f"Check if the command is waiting for user input",
        ],
    )


def validation_error(error_msg: str, invalid_params: Dict[str, Any] = None, tool_name: str = "tool") -> ToolError:
    """Create a VALIDATION_ERROR for invalid inputs."""
    context = {"tool": tool_name}
    if invalid_params:
        context["invalid_params"] = invalid_params

    return ToolError(
        error_type=ToolErrorType.VALIDATION_ERROR,
        message=f"{tool_name}: Validation error - {error_msg}",
        context=context,
        recoverable=True,
        suggested_recovery=[
            f"Verify the tool arguments match the expected schema",
            f"Check the tool documentation for required parameters",
        ],
    )