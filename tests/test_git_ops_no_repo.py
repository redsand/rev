
import json
import shutil
import tempfile
from pathlib import Path
import pytest
from rev import config
from rev.tools import git_ops

@pytest.fixture
def non_git_workspace():
    """Create a temporary workspace without .git."""
    # Use a temp dir outside the current repo to avoid picking up parent .git
    tmp_dir = tempfile.mkdtemp()
    workspace = Path(tmp_dir)
    
    # Create a dummy file
    (workspace / "foo.txt").write_text("bar")
    
    # Save old root
    old_root = config.ROOT
    config.set_workspace_root(workspace)
    
    yield workspace
    
    # Restore
    config.set_workspace_root(old_root)
    shutil.rmtree(tmp_dir)

def test_get_repo_context_no_git(non_git_workspace):
    # Ensure cache doesn't interfere
    git_ops.get_repo_context.__globals__.get("clear_provider_cache", lambda: None)()
    # Actually we need to clear the repo cache
    from rev.cache import get_repo_cache
    if get_repo_cache():
        get_repo_cache().set_context(None)

    result_json = git_ops.get_repo_context()
    result = json.loads(result_json)
    
    print(f"Result: {result}")
    
    # We expect graceful degradation (no error, just empty git info)
    assert "error" not in result
    assert result["status"] == ""
    assert result["log"] == ""
    assert len(result["top_level"]) > 0

def test_git_status_no_git(non_git_workspace):
    result_json = git_ops.git_status()
    result = json.loads(result_json)
    print(f"Git Status Result: {result}")
    
    # Expect explicit error about repo
    assert "Not a git repository" in result.get("error", "")
