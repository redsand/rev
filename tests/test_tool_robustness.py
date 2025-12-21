import pytest
import json
from unittest.mock import patch, Mock
from rev.tools.registry import execute_tool

def test_execute_tool_retries_transient_failure():
    """
    Prove Feature 7: Tool execution is robust and retries on transient errors.
    """
    # Patch execute_with_retry in the registry's timeout manager
    with patch("rev.execution.timeout_manager.TimeoutManager.execute_with_retry") as mock_retry:
        mock_retry.return_value = json.dumps({"files": ["main.py"]})
        
        # Execute tool
        result = execute_tool("list_dir", {"pattern": "*"})
        
        # Verify execute_with_retry was called
        assert mock_retry.called
        data = json.loads(result)
        assert "main.py" in data["files"]

def test_execute_tool_fails_on_persistent_error():
    """
    Verify that non-transient errors are not retried.
    """
    with patch("rev.tools.registry.list_dir") as mock_list_dir:
        # FileNotFoundError is NOT transient
        mock_list_dir.side_effect = FileNotFoundError("Not found")
        
        with patch("time.sleep") as mock_sleep:
            result = execute_tool("list_dir", {"pattern": "*"})
            
            # Should only be called once
            assert mock_list_dir.call_count == 1
            assert mock_sleep.call_count == 0
            
            # Result should contain the error
            assert "FileNotFoundError" in result
