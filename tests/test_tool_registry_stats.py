from rev.tools.registry import get_tool_stats, get_available_tools


def test_tool_stats_has_total_and_mcp_field():
    stats = get_tool_stats()
    assert "total_tools" in stats
    assert isinstance(stats["total_tools"], int)
    # mcp_server_count is best-effort; allow None or int
    assert stats.get("mcp_server_count") is None or isinstance(stats["mcp_server_count"], int)


def test_get_available_tools_not_empty():
    tools = get_available_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0
