#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) client for rev."""

import json
import os
from typing import Dict, Any, List, Optional


class MCPClient:
    """Client for Model Context Protocol servers."""

    def __init__(self, load_defaults: bool = True):
        self.servers = {}
        self.tools = {}

        # Load default MCP servers if enabled
        if load_defaults:
            self._load_default_servers()

    def add_server(self, name: str, command: str, args: List[str] = None) -> Dict[str, Any]:
        """Add an MCP server."""
        try:
            # Store server configuration
            self.servers[name] = {
                "command": command,
                "args": args or [],
                "connected": False
            }
            return {"added": name, "command": command}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def list_servers(self) -> Dict[str, Any]:
        """List configured MCP servers."""
        return {"servers": list(self.servers.keys())}

    def call_mcp_tool(self, server: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on an MCP server."""
        try:
            if server not in self.servers:
                return {"error": f"Server not found: {server}"}

            # For now, return a placeholder
            # Full MCP implementation would use stdio communication
            return {
                "mcp_call": True,
                "server": server,
                "tool": tool,
                "note": "MCP server communication would happen here"
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def _load_default_servers(self) -> None:
        """Load default MCP servers from configuration."""
        try:
            from rev.config import (
                DEFAULT_MCP_SERVERS,
                REMOTE_MCP_SERVERS,
                OPTIONAL_MCP_SERVERS,
                is_mcp_server_allowed
            )

            # Load default local MCP servers (npm packages)
            for name, config in DEFAULT_MCP_SERVERS.items():
                if config.get("enabled", True) and is_mcp_server_allowed(config):
                    self.add_server(
                        name=name,
                        command=config["command"],
                        args=config["args"]
                    )

            # Load remote MCP servers (SSE/HTTP endpoints)
            for name, config in REMOTE_MCP_SERVERS.items():
                if config.get("enabled", True) and is_mcp_server_allowed(config):
                    self.add_remote_server(
                        name=name,
                        url=config["url"],
                        description=config.get("description", ""),
                        category=config.get("category", "general")
                    )

            # Load optional servers only if environment variables are present
            # These are not affected by private mode as they require explicit user setup
            for name, config in OPTIONAL_MCP_SERVERS.items():
                if config.get("enabled", False):
                    env_vars = config.get("env_required", [])
                    # Only load if all required environment variables are set
                    if all(os.getenv(var) for var in env_vars):
                        self.add_server(
                            name=name,
                            command=config["command"],
                            args=config["args"]
                        )
        except ImportError:
            # Gracefully handle case where config is not available
            pass
        except Exception as e:
            # Log error but don't fail initialization
            print(f"Warning: Failed to load default MCP servers: {e}")

    def add_remote_server(self, name: str, url: str, description: str = "", category: str = "general") -> Dict[str, Any]:
        """
        Add a remote MCP server (SSE/HTTP endpoint).

        Args:
            name: Server name
            url: Server URL endpoint
            description: Server description
            category: Server category (e.g., 'code-understanding', 'security')

        Returns:
            Result dictionary
        """
        try:
            self.servers[name] = {
                "type": "remote",
                "url": url,
                "description": description,
                "category": category,
                "connected": False
            }
            return {"added": name, "url": url, "type": "remote"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def get_server_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific MCP server."""
        return self.servers.get(name)

    def enable_private_mode(self) -> Dict[str, Any]:
        """
        Enable private mode - disables all public MCP servers.
        Use this when working with confidential/proprietary code.

        Returns:
            Status dictionary with disabled server count
        """
        try:
            from rev.config import set_private_mode

            # Get current servers before enabling private mode
            current_servers = list(self.servers.keys())

            # Enable private mode
            set_private_mode(True)

            # Reload servers (will skip public ones)
            self.servers.clear()
            self.tools.clear()
            self._load_default_servers()

            # Get new server list
            new_servers = list(self.servers.keys())
            disabled_count = len(current_servers) - len(new_servers)

            return {
                "private_mode": True,
                "disabled_servers": disabled_count,
                "active_servers": new_servers,
                "message": f"Private mode enabled. {disabled_count} public MCP servers disabled."
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def disable_private_mode(self) -> Dict[str, Any]:
        """
        Disable private mode - re-enables all configured MCP servers.

        Returns:
            Status dictionary with enabled server count
        """
        try:
            from rev.config import set_private_mode

            # Get current servers before disabling private mode
            current_servers = list(self.servers.keys())

            # Disable private mode
            set_private_mode(False)

            # Reload servers (will include public ones)
            self.servers.clear()
            self.tools.clear()
            self._load_default_servers()

            # Get new server list
            new_servers = list(self.servers.keys())
            enabled_count = len(new_servers) - len(current_servers)

            return {
                "private_mode": False,
                "enabled_servers": enabled_count,
                "active_servers": new_servers,
                "message": f"Private mode disabled. {enabled_count} public MCP servers enabled."
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def get_private_mode_status(self) -> Dict[str, Any]:
        """
        Get current private mode status.

        Returns:
            Status dictionary with mode and server counts
        """
        try:
            from rev.config import get_private_mode

            is_private = get_private_mode()
            servers = self.list_servers()

            return {
                "private_mode": is_private,
                "server_count": len(servers.get("servers", [])),
                "servers": servers.get("servers", [])
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}


# Global MCP client instance
mcp_client = MCPClient()


def mcp_add_server(name: str, command: str, args: str = "") -> str:
    """Add an MCP server."""
    arg_list = args.split() if args else []
    result = mcp_client.add_server(name, command, arg_list)
    return json.dumps(result)


def mcp_list_servers() -> str:
    """List MCP servers."""
    result = mcp_client.list_servers()
    return json.dumps(result)


def mcp_call_tool(server: str, tool: str, arguments: str = "{}") -> str:
    """Call an MCP tool."""
    try:
        args_dict = json.loads(arguments)
        result = mcp_client.call_mcp_tool(server, tool, args_dict)
        return json.dumps(result)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON arguments: {e}"})


def mcp_enable_private_mode() -> str:
    """Enable private mode - disables all public MCP servers."""
    result = mcp_client.enable_private_mode()
    return json.dumps(result)


def mcp_disable_private_mode() -> str:
    """Disable private mode - re-enables all configured MCP servers."""
    result = mcp_client.disable_private_mode()
    return json.dumps(result)


def mcp_get_private_mode_status() -> str:
    """Get current private mode status."""
    result = mcp_client.get_private_mode_status()
    return json.dumps(result)
