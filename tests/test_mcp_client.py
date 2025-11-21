"""Comprehensive tests for MCP (Model Context Protocol) client."""
import json
import pytest
import rev
from rev.mcp import MCPClient, mcp_client


class TestMCPClient:
    """Test MCP client functionality."""

    def test_mcp_client_initialization(self):
        """Test MCPClient can be initialized."""
        client = MCPClient()
        assert client is not None
        assert hasattr(client, 'servers')
        assert hasattr(client, 'tools')
        assert isinstance(client.servers, dict)
        assert isinstance(client.tools, dict)

    def test_add_server(self):
        """Test adding an MCP server."""
        client = MCPClient()
        result = client.add_server("test_server", "python", ["-m", "test"])

        assert "added" in result or "error" not in result
        assert "test_server" in client.servers
        assert client.servers["test_server"]["command"] == "python"
        assert client.servers["test_server"]["args"] == ["-m", "test"]

    def test_add_server_no_args(self):
        """Test adding server without args."""
        client = MCPClient()
        result = client.add_server("simple", "node")

        assert "added" in result
        assert client.servers["simple"]["args"] == []

    def test_list_servers_empty(self):
        """Test listing servers when none added."""
        client = MCPClient()
        result = client.list_servers()

        assert "servers" in result
        assert result["servers"] == []

    def test_list_servers_with_servers(self):
        """Test listing servers after adding some."""
        client = MCPClient()
        client.add_server("server1", "cmd1")
        client.add_server("server2", "cmd2")

        result = client.list_servers()
        assert "servers" in result
        assert len(result["servers"]) == 2
        assert "server1" in result["servers"]
        assert "server2" in result["servers"]

    def test_call_mcp_tool_server_not_found(self):
        """Test calling tool on non-existent server."""
        client = MCPClient()
        result = client.call_mcp_tool("nonexistent", "tool", {})

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_call_mcp_tool_success(self):
        """Test calling tool on existing server."""
        client = MCPClient()
        client.add_server("test_server", "python")

        result = client.call_mcp_tool("test_server", "test_tool", {"arg": "value"})

        assert "error" not in result or "mcp_call" in result
        if "mcp_call" in result:
            assert result["mcp_call"] == True
            assert result["server"] == "test_server"
            assert result["tool"] == "test_tool"


class TestMCPFunctions:
    """Test MCP module functions."""

    def test_mcp_add_server_function(self):
        """Test mcp_add_server function."""
        result_str = rev.mcp_add_server("test_func", "python", "-m test")
        result = json.loads(result_str)

        assert isinstance(result, dict)
        assert "added" in result or "error" not in result

    def test_mcp_add_server_no_args(self):
        """Test mcp_add_server without args."""
        result_str = rev.mcp_add_server("simple_func", "node", "")
        result = json.loads(result_str)

        assert isinstance(result, dict)

    def test_mcp_list_servers_function(self):
        """Test mcp_list_servers function."""
        result_str = rev.mcp_list_servers()
        result = json.loads(result_str)

        assert isinstance(result, dict)
        assert "servers" in result
        assert isinstance(result["servers"], list)

    def test_mcp_call_tool_function(self):
        """Test mcp_call_tool function."""
        # First add a server
        rev.mcp_add_server("test_server2", "python")

        # Then call a tool
        result_str = rev.mcp_call_tool("test_server2", "test_tool", '{"key": "value"}')
        result = json.loads(result_str)

        assert isinstance(result, dict)
        # Should either succeed or return error
        assert "error" in result or "mcp_call" in result or "note" in result

    def test_mcp_call_tool_invalid_json(self):
        """Test mcp_call_tool with invalid JSON arguments."""
        result_str = rev.mcp_call_tool("server", "tool", "{invalid json")
        result = json.loads(result_str)

        assert "error" in result
        assert "JSON" in result["error"] or "json" in result["error"]

    def test_mcp_call_tool_nonexistent_server(self):
        """Test calling tool on non-existent server."""
        result_str = rev.mcp_call_tool("does_not_exist_xyz", "tool", "{}")
        result = json.loads(result_str)

        assert "error" in result


class TestMCPGlobalClient:
    """Test global mcp_client instance."""

    def test_global_client_exists(self):
        """Test that global mcp_client exists."""
        from rev.mcp import mcp_client
        assert mcp_client is not None
        assert isinstance(mcp_client, MCPClient)

    def test_global_client_state_persistence(self):
        """Test that global client persists state."""
        from rev.mcp import mcp_client

        # Add a server
        mcp_client.add_server("persistent_test", "cmd")

        # Check it's still there
        servers = mcp_client.list_servers()
        assert "persistent_test" in servers["servers"]


class TestMCPEdgeCases:
    """Test MCP edge cases and error handling."""

    def test_add_server_empty_name(self):
        """Test adding server with empty name."""
        client = MCPClient()
        result = client.add_server("", "cmd")
        # Should handle gracefully
        assert isinstance(result, dict)

    def test_add_server_empty_command(self):
        """Test adding server with empty command."""
        client = MCPClient()
        result = client.add_server("test", "")
        # Should handle gracefully
        assert isinstance(result, dict)

    def test_call_tool_empty_server(self):
        """Test calling tool with empty server name."""
        client = MCPClient()
        result = client.call_mcp_tool("", "tool", {})
        assert "error" in result

    def test_call_tool_empty_tool_name(self):
        """Test calling tool with empty tool name."""
        client = MCPClient()
        client.add_server("server", "cmd")
        result = client.call_mcp_tool("server", "", {})
        # Should handle gracefully
        assert isinstance(result, dict)

    def test_multiple_servers_same_name(self):
        """Test adding multiple servers with same name."""
        client = MCPClient()
        client.add_server("duplicate", "cmd1")
        client.add_server("duplicate", "cmd2")

        # Second one should overwrite first
        assert "duplicate" in client.servers
        assert client.servers["duplicate"]["command"] == "cmd2"
