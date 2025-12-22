#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bundle Capture System.

Captures task execution into a replayable bundle.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime


class BundleCapture:
    """Captures task execution events into a bundle."""

    def __init__(self):
        """Initialize bundle capture."""
        self.bundle = {
            "request": None,
            "tool_calls": [],
            "llm_calls": [],
            "file_modifications": [],
            "validations": [],
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "version": "1.0"
            }
        }

    def record_request(self, request: str) -> None:
        """Record the initial user request.

        Args:
            request: User's request string
        """
        self.bundle["request"] = request

    def record_tool_call(self, tool: str, params: Dict[str, Any], result: Any) -> None:
        """Record a tool call.

        Args:
            tool: Tool name
            params: Tool parameters
            result: Tool result
        """
        self.bundle["tool_calls"].append({
            "tool": tool,
            "params": params,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })

    def record_llm_call(self, messages: List[Dict], response: Dict, model: str) -> None:
        """Record an LLM call.

        Args:
            messages: Input messages
            response: LLM response
            model: Model name
        """
        self.bundle["llm_calls"].append({
            "messages": messages,
            "response": response,
            "model": model,
            "timestamp": datetime.now().isoformat(),
            "usage": response.get("usage", {})
        })

    def record_file_modification(
        self,
        file_path: str,
        operation: str,
        old_content: Optional[str] = None,
        new_content: Optional[str] = None
    ) -> None:
        """Record a file modification.

        Args:
            file_path: Path to modified file
            operation: Operation type (edit, write, delete)
            old_content: Original content (for edits)
            new_content: New content
        """
        self.bundle["file_modifications"].append({
            "file_path": file_path,
            "operation": operation,
            "old_content": old_content,
            "new_content": new_content,
            "timestamp": datetime.now().isoformat()
        })

    def record_validation(self, validator: str, result: Dict[str, Any]) -> None:
        """Record a validation result.

        Args:
            validator: Validator name (e.g., "pytest", "mypy")
            result: Validation result dictionary
        """
        self.bundle["validations"].append({
            "validator": validator,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })

    def get_bundle(self) -> Dict[str, Any]:
        """Get the captured bundle.

        Returns:
            Bundle dictionary
        """
        return self.bundle
