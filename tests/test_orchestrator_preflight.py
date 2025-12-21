import pytest
from pathlib import Path
from rev.models.task import Task
from rev.execution.orchestrator import _preflight_correct_task_paths

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a mock project root with a sample file."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").touch()
    return tmp_path

def test_preflight_handles_complex_descriptions(project_root: Path):
    """
    Verify preflight correctly extracts paths from complex task descriptions
    without crashing due to regex group errors.
    """
    task = Task(
        action_type="analyze",
        description="inspect the current structure of lib/analysts.py to understand the classes"
    )
    
    # Create the file the task is looking for
    (project_root / "lib").mkdir()
    (project_root / "lib" / "analysts.py").touch()

    ok, messages = _preflight_correct_task_paths(task=task, project_root=project_root)
    
    assert ok, f"Preflight failed unexpectedly with messages: {messages}"
    
    # Check that no "missing path" style errors were reported.
    error_indicators = ["ambiguous missing path", "missing path '"]
    found_errors = [m for m in messages if any(e in m for e in error_indicators)]
    assert not found_errors, f"Preflight reported unexpected path errors: {found_errors}"
    
    assert any("resolved missing path to 'lib/analysts.py'" in m for m in messages)

def test_preflight_fails_gracefully_on_missing_file(project_root: Path):
    """
    Verify preflight returns a clear error for a file that truly doesn't exist.
    """
    task = Task(
        action_type="read",
        description="Read the content of a non-existent-file.py"
    )

    ok, messages = _preflight_correct_task_paths(task=task, project_root=project_root)
    
    assert not ok
    assert "missing path 'non-existent-file.py'" in "".join(messages)