#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Centralized tool-output compression policy.

Keeps behavior predictable by routing all decisions through one policy object.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class ToolCompressionDecision:
    compress: bool
    reason: str
    inline_content: Optional[str] = None  # for strict mode edit window


class ToolCompressionPolicy:
    """Policy for whether/how to inline tool outputs into messages."""

    def __init__(self):
        self.inline_max_chars = _env_int("REV_TOOL_INLINE_MAX_CHARS", 4000)
        self.summary_target_chars = _env_int("REV_TOOL_SUMMARY_TARGET_CHARS", 400)
        self.compress_all = _env_bool("REV_COMPRESS_ALL_TOOL_OUTPUTS", False)
        self.read_file_inline_lines = _env_int("REV_READ_FILE_INLINE_LINES", 200)

        self.noisy_tools = {
            "run_tests",
            "run_cmd",
            "git_diff",
            "tree_view",
            "search_code",
            "rag_search",
            "run_all_analysis",
            "analyze_ast_patterns",
            "analyze_code_structures",
            "analyze_static_types",
            "scan_security_issues",
            "detect_secrets",
            "analyze_dependencies",
            "analyze_semantic_diff",
            "analyze_code_context",
        }

        self.never_compress = {"read_file_lines"}

    def decide(self, tool_name: str, output: str) -> ToolCompressionDecision:
        tool = (tool_name or "").lower()

        if tool in self.never_compress:
            return ToolCompressionDecision(compress=False, reason="never_compress")

        if self.compress_all:
            if tool == "read_file":
                window = self._read_file_window(output)
                return ToolCompressionDecision(compress=True, reason="compress_all_read_file_window", inline_content=window)
            return ToolCompressionDecision(compress=True, reason="compress_all")

        if tool == "read_file":
            return ToolCompressionDecision(compress=False, reason="read_file_inline")

        if tool in self.noisy_tools:
            return ToolCompressionDecision(compress=True, reason="noisy_tool")

        if output is not None and len(output) > self.inline_max_chars:
            return ToolCompressionDecision(compress=True, reason="size_threshold")

        return ToolCompressionDecision(compress=False, reason="default_inline")

    def _read_file_window(self, output: str) -> str:
        lines = (output or "").splitlines()
        head = lines[: self.read_file_inline_lines]
        tail = []
        if len(lines) > self.read_file_inline_lines:
            tail = ["...[truncated]..."]
        return "\n".join(head + tail) + ("\n" if output.endswith("\n") else "")


_POLICY: ToolCompressionPolicy | None = None


def get_tool_compression_policy() -> ToolCompressionPolicy:
    global _POLICY
    if _POLICY is None:
        _POLICY = ToolCompressionPolicy()
    return _POLICY

