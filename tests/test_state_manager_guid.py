import importlib.util
import pathlib
import re

# Dynamically load StateManager to avoid the top‑level rev.py shim conflict
_state_manager_path = pathlib.Path(__file__).parents[1] / "rev" / "execution" / "state_manager.py"
_spec = importlib.util.spec_from_file_location("rev.execution.state_manager", _state_manager_path)
_state_manager = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_state_manager)
StateManager = _state_manager.StateManager

# Import ExecutionPlan normally
from rev.models.task import ExecutionPlan


def test_state_manager_session_id_is_guid():
    """StateManager should generate a 32‑character hex GUID for session_id."""
    plan = ExecutionPlan()
    manager = StateManager(plan)
    guid = manager.session_id
    pattern = re.compile(r"^[0-9a-f]{32}$")
    assert pattern.fullmatch(guid) is not None, f"session_id '{guid}' does not match GUID pattern"
