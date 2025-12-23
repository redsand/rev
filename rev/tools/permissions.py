#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tool permissions and least privilege system for REV.

This module implements agent-level tool access control to prevent dangerous
operations based on agent role.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import yaml

from rev.debug_logger import get_logger


logger = get_logger()


class RiskLevel(Enum):
    """Risk levels for tool operations."""
    LOW = "low"  # read_file, list_dir, search_code
    MEDIUM = "medium"  # write_file, run_tests
    HIGH = "high"  # git_commit, run_cmd
    CRITICAL = "critical"  # git_push, delete_file


@dataclass
class PermissionDenial:
    """Record of a denied permission request."""
    agent_name: str
    tool_name: str
    tool_args: Dict[str, Any]
    reason: str
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class PermissionResult:
    """Result of a permission check."""
    allowed: bool
    reason: str
    risk_level: Optional[RiskLevel] = None
    requires_confirmation: bool = False


@dataclass
class AgentRole:
    """Definition of an agent role with tool permissions."""
    name: str
    description: str
    allowed_tools: List[str]  # List of tool names or "*" for all
    denied_tools: List[str] = field(default_factory=list)
    max_calls_per_session: Dict[str, int] = field(default_factory=dict)
    allowed_patterns: List[str] = field(default_factory=list)  # Regex patterns


@dataclass
class ToolPermission:
    """Permission configuration for a specific tool."""
    tool_name: str
    risk_level: RiskLevel
    requires_confirmation: bool = False
    dangerous_args_patterns: List[str] = field(default_factory=list)  # Regex for dangerous args


class PermissionPolicy:
    """Policy defining permissions for all agents and tools."""

    def __init__(self):
        self.default_policy: str = "deny"  # "allow" or "deny"
        self.agent_roles: Dict[str, AgentRole] = {}
        self.tool_permissions: Dict[str, ToolPermission] = {}
        self.require_confirmation: List[str] = []

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> tuple["PermissionPolicy", Optional[Exception]]:
        """Load policy from YAML file.

        Returns:
            Tuple of (policy, error). If error is not None, policy loading failed.
        """
        policy = cls()

        if not yaml_path.exists():
            logger.warning(f"Permission policy file not found: {yaml_path}. Using permissive defaults.")
            return policy, None

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                return policy, None

            # Load default policy
            policy.default_policy = data.get("default_policy", "deny")

            # Load agent roles
            agent_roles_data = data.get("agent_roles", {})
            for role_name, role_config in agent_roles_data.items():
                role = AgentRole(
                    name=role_name,
                    description=role_config.get("description", ""),
                    allowed_tools=role_config.get("allowed_tools", []),
                    denied_tools=role_config.get("denied_tools", []),
                    max_calls_per_session=role_config.get("max_calls_per_session", {}),
                )
                # Handle wildcard patterns like "analyze_*"
                role.allowed_patterns = [
                    tool for tool in role.allowed_tools if "*" in tool
                ]
                policy.agent_roles[role_name] = role

            # Load tool risk levels
            tool_risk_levels = data.get("tool_risk_levels", {})
            for tool_name, risk_str in tool_risk_levels.items():
                try:
                    risk_level = RiskLevel(risk_str.lower())
                except ValueError:
                    risk_level = RiskLevel.MEDIUM
                    logger.warning(f"Invalid risk level for {tool_name}: {risk_str}, using MEDIUM")

                policy.tool_permissions[tool_name] = ToolPermission(
                    tool_name=tool_name,
                    risk_level=risk_level,
                )

            # Load confirmation requirements
            policy.require_confirmation = data.get("require_confirmation", [])

            return policy, None

        except Exception as e:
            # REV-011: Return the error so caller can decide whether to fail-open or fail-closed
            logger.error(f"Failed to load permission policy from {yaml_path}: {e}")
            return policy, e

    def get_agent_role(self, agent_name: str) -> Optional[AgentRole]:
        """Get agent role by name, with fallback to 'default' or 'executor'."""
        if agent_name in self.agent_roles:
            return self.agent_roles[agent_name]

        # Try common fallbacks
        if "default" in self.agent_roles:
            return self.agent_roles["default"]

        if "executor" in self.agent_roles:
            return self.agent_roles["executor"]

        return None

    def get_tool_permission(self, tool_name: str) -> Optional[ToolPermission]:
        """Get tool permission configuration."""
        return self.tool_permissions.get(tool_name)


class PermissionManager:
    """Manages tool permissions and access control."""

    def __init__(self, policy_path: Optional[Path] = None):
        """Initialize permission manager with policy.

        Args:
            policy_path: Path to tool_policy.yaml. If None, looks in current directory.
        """
        if policy_path is None:
            policy_path = Path.cwd() / "tool_policy.yaml"

        # REV-011: from_yaml now returns (policy, error) tuple
        self.policy, self.policy_load_error = PermissionPolicy.from_yaml(policy_path)
        self.denial_log: List[PermissionDenial] = []
        self.call_counts: Dict[str, Dict[str, int]] = {}  # agent -> {tool: count}

        if self.policy_load_error:
            logger.error(f"Failed to load policy from {policy_path}: {self.policy_load_error}")
        else:
            logger.info(f"Initialized PermissionManager with policy from {policy_path}")

    def check_permission(self, agent_name: str, tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> PermissionResult:
        """Check if agent has permission to use tool.

        Args:
            agent_name: Name of the agent requesting permission
            tool_name: Name of the tool to execute
            tool_args: Optional arguments passed to tool (for dangerous pattern checking)

        Returns:
            PermissionResult indicating whether permission is granted
        """
        # If no policy is loaded, allow everything (backward compatibility)
        if not self.policy.agent_roles:
            return PermissionResult(allowed=True, reason="No policy loaded, allowing by default")

        # Get agent role
        agent_role = self.policy.get_agent_role(agent_name)
        if agent_role is None:
            # No role defined for this agent
            if self.policy.default_policy == "allow":
                return PermissionResult(allowed=True, reason=f"Agent {agent_name} not in policy, default allow")
            else:
                return PermissionResult(allowed=False, reason=f"Agent {agent_name} not in policy, default deny")

        # Check if tool is explicitly denied
        if tool_name in agent_role.denied_tools:
            return PermissionResult(allowed=False, reason=f"Tool {tool_name} explicitly denied for {agent_name}")

        # Check for dangerous command patterns in denied_tools
        if tool_args:
            for denied_pattern in agent_role.denied_tools:
                if self._matches_dangerous_pattern(tool_name, tool_args, denied_pattern):
                    return PermissionResult(allowed=False, reason=f"Tool call matches denied pattern: {denied_pattern}")

        # Check if tool is explicitly allowed
        if "*" in agent_role.allowed_tools:
            # Agent has access to all tools (except explicitly denied ones)
            result = PermissionResult(allowed=True, reason=f"Agent {agent_name} has wildcard access")
        elif tool_name in agent_role.allowed_tools:
            result = PermissionResult(allowed=True, reason=f"Tool {tool_name} explicitly allowed for {agent_name}")
        else:
            # Check if tool matches any allowed patterns (e.g., "analyze_*")
            matched = False
            for pattern in agent_role.allowed_patterns:
                if self._matches_tool_pattern(tool_name, pattern):
                    matched = True
                    break

            if matched:
                result = PermissionResult(allowed=True, reason=f"Tool {tool_name} matches allowed pattern")
            else:
                result = PermissionResult(allowed=False, reason=f"Tool {tool_name} not in allowed list for {agent_name}")

        # Check call count limits
        if result.allowed and tool_name in agent_role.max_calls_per_session:
            max_calls = agent_role.max_calls_per_session[tool_name]
            current_count = self._get_call_count(agent_name, tool_name)
            if current_count >= max_calls:
                result = PermissionResult(
                    allowed=False,
                    reason=f"Call limit reached for {tool_name}: {current_count}/{max_calls}"
                )

        # Check if confirmation is required
        if result.allowed:
            tool_perm = self.policy.get_tool_permission(tool_name)
            if tool_perm:
                result.risk_level = tool_perm.risk_level
                if tool_name in self.policy.require_confirmation:
                    result.requires_confirmation = True

        # Increment call count if allowed
        if result.allowed:
            self._increment_call_count(agent_name, tool_name)

        return result

    def log_denial(self, agent_name: str, tool_name: str, tool_args: Dict[str, Any], reason: str):
        """Log a denied permission request.

        Args:
            agent_name: Agent that requested permission
            tool_name: Tool that was denied
            tool_args: Arguments passed to tool
            reason: Reason for denial
        """
        import time

        denial = PermissionDenial(
            agent_name=agent_name,
            tool_name=tool_name,
            tool_args=tool_args,
            reason=reason,
            timestamp=time.time(),
        )
        self.denial_log.append(denial)

        logger.warning(f"Permission denied: {agent_name} attempted {tool_name}. Reason: {reason}")

    def get_denial_log(self) -> List[PermissionDenial]:
        """Get all permission denials in the session."""
        return self.denial_log.copy()

    def export_denial_log(self, path: Path):
        """Export denial log to JSON file for review."""
        log_data = [denial.to_dict() for denial in self.denial_log]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)
        logger.info(f"Exported {len(self.denial_log)} permission denials to {path}")

    def reset_call_counts(self):
        """Reset all call counts (for testing or new sessions)."""
        self.call_counts = {}

    def _get_call_count(self, agent_name: str, tool_name: str) -> int:
        """Get current call count for agent/tool combination."""
        return self.call_counts.get(agent_name, {}).get(tool_name, 0)

    def _increment_call_count(self, agent_name: str, tool_name: str):
        """Increment call count for agent/tool combination."""
        if agent_name not in self.call_counts:
            self.call_counts[agent_name] = {}
        self.call_counts[agent_name][tool_name] = self._get_call_count(agent_name, tool_name) + 1

    def _matches_tool_pattern(self, tool_name: str, pattern: str) -> bool:
        """Check if tool name matches a pattern (e.g., 'analyze_*')."""
        regex_pattern = pattern.replace("*", ".*")
        regex_pattern = f"^{regex_pattern}$"
        return re.match(regex_pattern, tool_name) is not None

    def _matches_dangerous_pattern(self, tool_name: str, tool_args: Dict[str, Any], denied_pattern: str) -> bool:
        """Check if tool call matches a dangerous pattern.

        Examples:
            denied_pattern = "run_cmd: [\"rm -rf\", \"del /f /s /q\"]"
            denied_pattern = "git_push --force"
        """
        # Parse the denied pattern
        if ":" in denied_pattern:
            # Format: "tool_name: [\"pattern1\", \"pattern2\"]"
            parts = denied_pattern.split(":", 1)
            pattern_tool_name = parts[0].strip()
            if pattern_tool_name != tool_name:
                return False

            # Extract dangerous argument patterns
            try:
                dangerous_args = eval(parts[1].strip())
                if isinstance(dangerous_args, list):
                    # Check if any tool argument contains the dangerous pattern
                    for arg_name, arg_value in tool_args.items():
                        arg_str = str(arg_value)
                        for dangerous_pattern in dangerous_args:
                            if dangerous_pattern.lower() in arg_str.lower():
                                return True
                return False
            except Exception:
                # If parsing fails, treat whole thing as a simple pattern
                return parts[1].strip().lower() in str(tool_args).lower()
        else:
            # Simple pattern like "git_push --force"
            # Check if pattern appears in tool name or arguments
            pattern_lower = denied_pattern.lower()
            if pattern_lower in tool_name.lower():
                return True
            for arg_value in tool_args.values():
                if pattern_lower in str(arg_value).lower():
                    return True
            return False


# Global singleton for easy access
_GLOBAL_PERMISSION_MANAGER: Optional[PermissionManager] = None
_GLOBAL_PERMISSION_MANAGER_PATH: Optional[Path] = None


def get_permission_manager(policy_path: Optional[Path] = None) -> PermissionManager:
    """Get or create the global permission manager.

    Args:
        policy_path: Path to policy file. If None, uses default location.

    Returns:
        The global PermissionManager instance
    """
    global _GLOBAL_PERMISSION_MANAGER, _GLOBAL_PERMISSION_MANAGER_PATH

    # Recreate manager if path has changed or doesn't exist
    if policy_path is None:
        policy_path = Path.cwd() / "tool_policy.yaml"

    if _GLOBAL_PERMISSION_MANAGER is None or _GLOBAL_PERMISSION_MANAGER_PATH != policy_path:
        _GLOBAL_PERMISSION_MANAGER = PermissionManager(policy_path)
        _GLOBAL_PERMISSION_MANAGER_PATH = policy_path

    return _GLOBAL_PERMISSION_MANAGER


def reset_permission_manager():
    """Reset the global permission manager (mainly for testing)."""
    global _GLOBAL_PERMISSION_MANAGER, _GLOBAL_PERMISSION_MANAGER_PATH
    _GLOBAL_PERMISSION_MANAGER = None
    _GLOBAL_PERMISSION_MANAGER_PATH = None
