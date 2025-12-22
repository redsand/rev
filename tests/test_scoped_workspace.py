"""Tests for scoped workspace and set_workdir functionality."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from rev import config
from rev.workspace import get_workspace, init_workspace, WorkspacePathError
from rev.tools.registry import execute_tool

@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    old_root = get_workspace().root
    workspace_dir = Path(tempfile.mkdtemp())
    # Create structure
    (workspace_dir / "apps" / "server").mkdir(parents=True)
    (workspace_dir / "apps" / "client").mkdir(parents=True)
    (workspace_dir / "root_file.txt").write_text("root content")
    (workspace_dir / "apps" / "server" / "server_file.txt").write_text("server content")
    
    init_workspace(workspace_dir)
    yield workspace_dir
    shutil.rmtree(workspace_dir)
    init_workspace(old_root)

def test_resolve_path_defaults_to_root(temp_workspace):
    ws = get_workspace()
    # Relative path should resolve to root
    resolved = ws.resolve_path("root_file.txt")
    assert resolved.abs_path == temp_workspace / "root_file.txt"
    assert resolved.rel_path == "root_file.txt"

def test_set_workdir_changes_resolution(temp_workspace):
    ws = get_workspace()
    # Set workdir to apps/server
    ws.set_working_dir("apps/server")
    
    # Relative path should now resolve to apps/server
    resolved = ws.resolve_path("server_file.txt")
    assert resolved.abs_path == temp_workspace / "apps" / "server" / "server_file.txt"
    assert resolved.rel_path == "apps/server/server_file.txt"

def test_set_workdir_via_tool(temp_workspace):
    # Set workdir via tool
    result = execute_tool("set_workdir", {"path": "apps/client"})
    assert "Working directory set to: apps/client" in result
    
    ws = get_workspace()
    assert ws.current_working_dir == temp_workspace / "apps" / "client"

def test_set_workdir_validation(temp_workspace):
    ws = get_workspace()
    # Should fail for non-existent directory
    with pytest.raises(WorkspacePathError):
        ws.set_working_dir("non_existent")
    
    # Should fail for file
    with pytest.raises(WorkspacePathError):
        ws.set_working_dir("root_file.txt")

def test_absolute_path_ignores_workdir(temp_workspace):
    ws = get_workspace()
    ws.set_working_dir("apps/server")
    
    # Absolute path (relative to root for our tools)
    # resolve_path treats paths starting with '/' as absolute if supported, 
    # but here we test the path relative to root vs relative to CWD.
    
    # Path with leading '/' is usually absolute in resolve_path logic if not on Windows
    # On Windows it depends. Let's use a path that is clearly absolute.
    abs_path = (temp_workspace / "root_file.txt").resolve()
    resolved = ws.resolve_path(str(abs_path))
    assert resolved.abs_path == abs_path
