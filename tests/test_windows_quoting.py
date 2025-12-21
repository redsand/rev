import os
import subprocess
import shlex
import pytest
from rev.tools.utils import quote_cmd_arg

def test_quote_cmd_arg_windows_behavior():
    """
    Regression test for Windows path quoting issue.
    Verifies that quote_cmd_arg produces cmd.exe compatible quoting on Windows
    and standard shlex quoting on POSIX.
    """
    path = r"C:\Users\champ\path\to\file.py"
    
    if os.name == 'nt':
        # On Windows, it should NOT have single quotes (which shlex.quote adds)
        # unless there are spaces, in which case it uses double quotes.
        quoted = quote_cmd_arg(path)
        assert "'" not in quoted
        assert '"' not in quoted # No spaces, so no quotes needed
        assert quoted == path
        
        # Test with spaces
        path_with_spaces = r"C:\Path With Spaces\file.py"
        quoted_spaces = quote_cmd_arg(path_with_spaces)
        assert quoted_spaces == f'"{path_with_spaces}"'
        
        # Test with drive letter only
        path_drive = "C:\\"
        quoted_drive = quote_cmd_arg(path_drive)
        assert quoted_drive == path_drive # No spaces, no quotes
        
        # Verify it actually works with a real shell command
        # (echo will print the path without quotes if they were stripped by the shell)
        result = subprocess.run(f"echo {quoted_spaces}", shell=True, capture_output=True, text=True)
        # cmd.exe echo includes quotes if they were part of the argument
        assert path_with_spaces in result.stdout
    else:
        # On POSIX, it should match shlex.quote
        quoted = quote_cmd_arg(path)
        assert quoted == shlex.quote(path)

def test_quote_cmd_arg_cross_platform(monkeypatch):
    """
    Test the logic by mocking os.name to ensure both branches are covered
    regardless of the host OS.
    """
    path = r"C:\test\path.py"
    
    # Mock Windows
    monkeypatch.setattr(os, "name", "nt")
    assert quote_cmd_arg(path) == path
    
    # Mock POSIX
    monkeypatch.setattr(os, "name", "posix")
    assert quote_cmd_arg(path) == f"'{path}'"

if __name__ == "__main__":
    pytest.main([__name__])
