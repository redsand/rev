#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tool call ledger and execution history tracking."""

import json
import hashlib
import time
import pathlib
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, asdict, field

from rev.debug_logger import get_logger


@dataclass
class ToolCallEvent:
    """Represents a single tool execution event."""
    timestamp: float
    tool: str
    arguments: Dict[str, Any]
    result: str
    duration_ms: float
    agent_name: str
    status: str = "success"  # success, error, blocked
    id: str = field(default_factory=lambda: hashlib.md5(str(time.time()).encode()).hexdigest()[:8])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_signature(self) -> str:
        """Return a signature representing the action (tool + key args)."""
        # Canonicalize args for signature
        sig_args = {}
        for k in sorted(self.arguments.keys()):
            val = self.arguments[k]
            if isinstance(val, (str, int, float, bool)) or val is None:
                sig_args[k] = val
        
        args_str = json.dumps(sig_args, sort_keys=True)
        return f"{self.tool}({args_str})"


class ToolCallLedger:
    """Records every tool call as structured events and provides history insights."""

    def __init__(self):
        self.events: List[ToolCallEvent] = []
        self._lock_files: Set[str] = set()
        self.logger = get_logger()

    def record(
        self,
        tool: str,
        arguments: Dict[str, Any],
        result: str,
        duration_ms: float,
        agent_name: str,
        status: str = "success"
    ) -> ToolCallEvent:
        """Record a tool call event."""
        event = ToolCallEvent(
            timestamp=time.time(),
            tool=tool,
            arguments=arguments,
            result=result,
            duration_ms=duration_ms,
            agent_name=agent_name,
            status=status
        )
        self.events.append(event)
        
        # Track inspected files (read operations)
        if tool in {"read_file", "read_file_lines", "get_file_info", "file_exists"}:
            path = arguments.get("path")
            if path:
                self._lock_files.add(str(path))
        
        return event

    def get_recent_actions(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return the last n actions as structured data."""
        return [e.to_dict() for e in self.events[-n:]]

    def get_files_inspected(self) -> Dict[str, int]:
        """Return a mapping of file paths to inspection counts."""
        inspected = {}
        for event in self.events:
            if event.tool in {"read_file", "read_file_lines", "get_file_info", "file_exists"}:
                path = event.arguments.get("path")
                if path:
                    inspected[str(path)] = inspected.get(str(path), 0) + 1
        return inspected

    def get_blocked_action_sigs(self) -> List[str]:
        """Return signatures of tool calls that were blocked."""
        return [e.get_signature() for e in self.events if e.status == "blocked"]

    def get_last_verification_status(self) -> Optional[Dict[str, Any]]:
        """Find the last verification-related result."""
        for event in reversed(self.events):
            if event.tool in {"run_tests", "run_cmd"} or "verify" in event.tool:
                try:
                    return json.loads(event.result)
                except Exception:
                    return {"raw_result": event.result}
        return None


# Global singleton ledger and cache
_GLOBAL_LEDGER = ToolCallLedger()

def get_ledger() -> ToolCallLedger:
    return _GLOBAL_LEDGER
