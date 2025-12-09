#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP (Model Context Protocol) client for rev."""

from .client import (
    MCPClient,
    mcp_client,
    mcp_add_server,
    mcp_list_servers,
    mcp_call_tool,
    mcp_enable_private_mode,
    mcp_disable_private_mode,
    mcp_get_private_mode_status,
)

__all__ = [
    "MCPClient",
    "mcp_client",
    "mcp_add_server",
    "mcp_list_servers",
    "mcp_call_tool",
    "mcp_enable_private_mode",
    "mcp_disable_private_mode",
    "mcp_get_private_mode_status",
]
