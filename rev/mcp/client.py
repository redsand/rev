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
            from rev.config import DEFAULT_MCP_SERVERS, OPTIONAL_MCP_SERVERS, PRIVATE_MODE

            # Check if private mode is enabled
            if PRIVATE_MODE:
                print("Private mode enabled - public MCP servers disabled")

            # Load default servers (enabled by default, no API keys required)
            for name, config in DEFAULT_MCP_SERVERS.items():
                # Skip public servers if in private mode
                if PRIVATE_MODE and config.get("public", False):
                    continue

                if config.get("enabled", True):
                    self.add_server(
                        name=name,
                        command=config["command"],
                        args=config["args"]
                    )

            # Load optional servers only if environment variables are present
            # Private servers (with API keys) are always allowed even in private mode
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

    def get_server_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific MCP server."""
        return self.servers.get(name)


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
