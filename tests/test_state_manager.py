import re

import pytest

from rev.execution.state_manager import StateManager
from rev.models.task import ExecutionPlan


def test_state_manager_session_id_is_guid():
    """StateManager should generate a 32-character hex GUID for session_id."""
    plan = ExecutionPlan()
    manager = StateManager(plan)
    guid = manager.session_id
    # GUID should be 32 hex characters (UUID4 hex)
    pattern = re.compile(r"^[0-9a-f]{32}$")
    assert pattern.fullmatch(guid) is not None, f"session_id '{guid}' does not match GUID pattern"
