from rev.tools import registry


def test_run_cmd_missing_cmd_field():
    result = registry.execute_tool("run_cmd", {"timeout": 5})
    assert isinstance(result, str)
    assert "missing required field" in result
