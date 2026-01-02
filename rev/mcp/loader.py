#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP server loader for rev (package-scoped to avoid name collisions)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from rev.debug_logger import get_logger


def _load_mcp_config(root: Path) -> List[Dict[str, Any]]:
    """Load MCP server configs from .rev/config.yml or rev.toml (if present)."""
    configs: List[Dict[str, Any]] = []
    yaml_config = root / ".rev" / "config.yml"
    toml_config = root / "rev.toml"

    try:
        if yaml_config.exists():
            import yaml
            data = yaml.safe_load(yaml_config.read_text())
            servers = data.get("mcpServers") if isinstance(data, dict) else None
            if isinstance(servers, list):
                configs.extend(servers)
        elif toml_config.exists():
            try:
                import tomllib as toml
                data = toml.loads(toml_config.read_text())
            except ImportError:
                import toml
                data = toml.loads(toml_config.read_text())
            servers = data.get("mcpServers") if isinstance(data, dict) else None
            if isinstance(servers, list):
                configs.extend(servers)
    except Exception as e:
        get_logger().log("mcp", "LOAD_ERROR", {"error": str(e)}, "ERROR")
    return configs


def _register_entry(entry: Dict[str, Any]) -> Optional[str]:
    """Register an MCP entry with the in-process client registry."""
    try:
        from rev.mcp.client import mcp_client
    except Exception as e:  # pragma: no cover - defensive import guard
        get_logger().log("mcp", "REGISTER_ERROR", {"error": str(e)}, "ERROR")
        return None

    name = entry.get("name") or entry.get("id") or "mcp"
    if entry.get("url"):
        mcp_client.add_remote_server(
            name=name,
            url=entry["url"],
            description=entry.get("description", ""),
            category=entry.get("category", "general"),
        )
    elif entry.get("command"):
        mcp_client.add_server(
            name=name,
            command=entry["command"],
            args=entry.get("args", []),
        )
    return name


def _start_mcp_server(entry: Dict[str, Any]) -> Optional[subprocess.Popen]:
    """Start a single MCP server based on config entry."""
    name = entry.get("name") or "mcp"
    cmd = entry.get("command")
    args = entry.get("args", [])
    env = os.environ.copy()
    env.update(entry.get("env", {}))
    if not cmd:
        return None
    try:
        proc = subprocess.Popen([cmd, *args], env=env)
        return proc
    except Exception as e:
        get_logger().log("mcp", "START_ERROR", {"server": name, "error": str(e)}, "ERROR")
        return None


def start_mcp_servers(root: Path, enable: bool = True, register: bool = True) -> List[subprocess.Popen]:
    """Load MCP config and start servers. Returns list of Popen handles."""
    if not enable:
        return []

    servers = _load_mcp_config(root)
    procs: List[subprocess.Popen] = []

    for entry in servers:
        if register:
            _register_entry(entry)
        proc = _start_mcp_server(entry)
        if proc:
            procs.append(proc)
            get_logger().log("mcp", "STARTED", {"server": entry.get("name"), "pid": proc.pid}, "INFO")
    return procs


def stop_mcp_servers(procs: List[subprocess.Popen]) -> None:
    """Terminate spawned MCP servers gracefully."""
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
