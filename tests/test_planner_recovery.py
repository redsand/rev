"""
Tests for the planner's ability to recover from malformed LLM responses.
"""

import json
from unittest.mock import MagicMock

import pytest

from rev.execution import planner
from rev.models.task import ExecutionPlan

def test_planner_recovers_from_malformed_json(monkeypatch):
    """
    Given the LLM returns a malformed JSON plan,
    And then returns a valid plan on the second attempt,
    The planner should retry and successfully parse the second response.
    """
    # Arrange
    malformed_json = "Here is the plan:\n[{{\"description\": \"Task 1\""  # Incomplete JSON
    valid_plan_data = [{"description": "Corrected Task 1", "action_type": "review", "complexity": "low"}, {"description": "Corrected Task 2", "action_type": "add", "complexity": "low"}]
    valid_json = json.dumps(valid_plan_data)

    # Mock ollama_chat to return bad JSON first, then good JSON
    mock_responses = [
        {"message": {"content": malformed_json}},
        {"message": {"content": valid_json}},
    ]
    
    # Use a mock that can be called multiple times and returns different values
    mock_chat = MagicMock(side_effect=mock_responses)
    
    # We only need to patch the underlying chat function that is called in all paths.
    monkeypatch.setattr(planner, "ollama_chat", mock_chat)


    # Act
    plan = planner.planning_mode(user_request="test recovery", enable_advanced_analysis=False)

    # Assert
    assert mock_chat.call_count == 2, "LLM should have been called twice (initial + retry)"
    assert isinstance(plan, ExecutionPlan)
    assert len(plan.tasks) >= 2, "Plan should have at least the two corrected tasks"
    assert plan.tasks[0].description == "Corrected Task 1"
    assert plan.tasks[1].description == "Corrected Task 2"


def test_planner_fails_after_max_retries(monkeypatch):
    """
    Given the LLM repeatedly returns malformed JSON,
    The planner should raise a RuntimeError after exhausting all retry attempts.
    """
    # Arrange
    malformed_json = "This is not JSON"

    # Mock ollama_chat to always return bad data
    mock_responses = [
        {"message": {"content": malformed_json}},
        {"message": {"content": malformed_json}},
        {"message": {"content": malformed_json}}, # Corresponds to max_parse_retries=2 + initial attempt
    ]
    
    mock_chat = MagicMock(side_effect=mock_responses)
    
    monkeypatch.setattr(planner, "ollama_chat", mock_chat)

    # Act & Assert
    with pytest.raises(RuntimeError, match="Could not parse a valid plan"):
        planner.planning_mode(user_request="test failure", enable_advanced_analysis=False)
    
    assert mock_chat.call_count == 3, "LLM should have been called for the initial attempt + 2 retries"
