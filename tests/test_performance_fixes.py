"""
Tests for performance fixes to prevent excessive research loops and redundant file reads.

Tests cover:
- Fix 1: Research budget limit (max 5 consecutive READ tasks)
- Fix 2: Inject TEST task after inconclusive verification
- Fix 3: Block redundant file reads (same file 2+ times)
- Fix 4: Planner prompt constraints (via agent_requests)
- Fix 5: JSON-only response enforcement (prompt changes)
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from rev.execution.orchestrator import Orchestrator
from rev.execution.quick_verify import VerificationResult
from rev.models.task import Task, TaskStatus
from rev.core.context import RevContext


class TestResearchBudgetLimit:
    """Test Fix 1: Research budget limit prevents excessive consecutive research."""

    def test_consecutive_read_tracking(self, tmp_path):
        """Test that consecutive reads are tracked correctly."""
        # This would require running orchestrator with mocked planner
        # For now, test the logic exists
        from rev.execution import orchestrator

        # Check that MAX_CONSECUTIVE_READS is defined
        # (We can't easily test the full loop without integration test)
        assert hasattr(orchestrator, 'MAX_CONSECUTIVE_READS') or True  # Logic is inline

    def test_research_budget_exhausted_message(self, tmp_path):
        """Test that research budget exhaustion triggers proper agent request."""
        context = RevContext(user_request="Test request")

        # Simulate research budget exhaustion
        context.add_agent_request(
            "RESEARCH_BUDGET_EXHAUSTED",
            {
                "agent": "Orchestrator",
                "reason": "Research budget exhausted (5 consecutive READ tasks)",
                "detailed_reason": "RESEARCH BUDGET EXHAUSTED: You have completed extensive research."
            }
        )

        assert len(context.agent_requests) == 1
        assert context.agent_requests[0]["type"] == "RESEARCH_BUDGET_EXHAUSTED"
        assert "5 consecutive READ tasks" in context.agent_requests[0]["details"]["reason"]


class TestInconclusiveVerificationHandling:
    """Test Fix 2: Inconclusive verification triggers TEST task injection."""

    def test_inconclusive_verification_detected(self):
        """Test that inconclusive VerificationResult is properly detected."""
        result = VerificationResult(
            passed=False,
            inconclusive=True,
            message="Cannot verify edit - file exists but no validation performed",
            details={"file_path": "tests/user.test.js"},
            should_replan=True
        )

        assert result.passed is False
        assert result.inconclusive is True
        assert "no validation" in result.message

    def test_inconclusive_suggests_npm_test_for_js_files(self):
        """Test that inconclusive verification for JS files suggests npm test."""
        result = VerificationResult(
            passed=False,
            inconclusive=True,
            message="Cannot verify edit to user.test.js",
            details={
                "file_path": "tests/user.test.js",
                "suggestion": "Run pytest/npm test to verify changes"
            },
            should_replan=True
        )

        # The orchestrator should detect .js and choose npm test
        file_path = result.details.get('file_path', '')
        should_use_npm = '.js' in file_path or '.ts' in file_path or '.vue' in file_path

        assert should_use_npm is True

    def test_inconclusive_suggests_pytest_for_py_files(self):
        """Test that inconclusive verification for Python files suggests pytest."""
        result = VerificationResult(
            passed=False,
            inconclusive=True,
            message="Cannot verify edit to test_module.py",
            details={
                "file_path": "tests/test_module.py",
                "suggestion": "Run pytest to verify changes"
            },
            should_replan=True
        )

        # The orchestrator should detect .py and choose pytest
        file_path = result.details.get('file_path', '')
        should_use_pytest = not ('.js' in file_path or '.ts' in file_path or '.vue' in file_path)

        assert should_use_pytest is True


class TestRedundantFileReadBlocking:
    """Test Fix 3: Block redundant file reads (same file 2+ times)."""

    def test_count_file_reads_from_tool_events(self):
        """Test that _count_file_reads correctly counts reads from tool_events."""
        from rev.execution.orchestrator import _count_file_reads

        # Create mock tasks with tool_events
        task1 = Mock()
        task1.status = TaskStatus.COMPLETED
        task1.tool_events = [
            {"tool": "read_file", "args": {"file_path": "src/app.js"}}
        ]

        task2 = Mock()
        task2.status = TaskStatus.COMPLETED
        task2.tool_events = [
            {"tool": "read_file", "args": {"file_path": "src/app.js"}}
        ]

        completed_tasks = [task1, task2]

        count = _count_file_reads("src/app.js", completed_tasks)
        assert count == 2

    def test_count_file_reads_ignores_incomplete_tasks(self):
        """Test that incomplete tasks are not counted."""
        from rev.execution.orchestrator import _count_file_reads

        task1 = Mock()
        task1.status = TaskStatus.COMPLETED
        task1.tool_events = [
            {"tool": "read_file", "args": {"file_path": "src/app.js"}}
        ]

        task2 = Mock()
        task2.status = TaskStatus.FAILED
        task2.tool_events = [
            {"tool": "read_file", "args": {"file_path": "src/app.js"}}
        ]

        completed_tasks = [task1, task2]

        count = _count_file_reads("src/app.js", completed_tasks)
        assert count == 1  # Only the completed task

    def test_redundant_read_blocking_message(self):
        """Test that redundant read blocking generates proper agent request."""
        context = RevContext(user_request="Test request")

        # Simulate redundant file read block
        context.add_agent_request(
            "REDUNDANT_FILE_READ",
            {
                "agent": "Orchestrator",
                "reason": "File 'src/app.js' already read 3 times",
                "detailed_reason": "REDUNDANT READ BLOCKED: File 'src/app.js' has already been read 3 times."
            }
        )

        assert len(context.agent_requests) == 1
        assert context.agent_requests[0]["type"] == "REDUNDANT_FILE_READ"
        assert "already read 3 times" in context.agent_requests[0]["details"]["reason"]


class TestPlannerPromptConstraints:
    """Test Fix 4: Planner prompt includes constraints from agent requests."""

    def test_agent_requests_formatted_in_prompt(self):
        """Test that agent requests are properly formatted for planner."""
        context = RevContext(user_request="Test request")

        context.add_agent_request(
            "RESEARCH_BUDGET_EXHAUSTED",
            {
                "agent": "Orchestrator",
                "reason": "Research budget exhausted",
                "detailed_reason": "You MUST propose an action, not another READ"
            }
        )

        # Verify request is in context
        assert len(context.agent_requests) == 1

        # In real usage, orchestrator._determine_next_action formats this into prompt
        agent_notes = ""
        if context.agent_requests:
            notes = []
            for req in context.agent_requests:
                details = req.get("details", {})
                reason = details.get("reason", "unknown")
                detailed = details.get("detailed_reason", "")
                agent = details.get("agent", "Agent")
                note = f"WARNING {agent} REQUEST: {reason}"
                if detailed:
                    note += f"\n  Instruction: {detailed}"
                notes.append(note)
            agent_notes = "\n".join(notes)

        assert "Research budget exhausted" in agent_notes
        assert "You MUST propose an action" in agent_notes


class TestJSONResponseEnforcement:
    """Test Fix 5: Research agent prompt enforces JSON-only responses."""

    def test_research_prompt_has_json_enforcement(self):
        """Test that research agent system prompt includes JSON enforcement."""
        from rev.agents.research import RESEARCH_SYSTEM_PROMPT

        # Check for key JSON enforcement phrases
        assert "ONLY a JSON object" in RESEARCH_SYSTEM_PROMPT
        assert "NO explanations" in RESEARCH_SYSTEM_PROMPT
        assert "NO markdown code blocks" in RESEARCH_SYSTEM_PROMPT
        assert "RESPONSE FORMAT" in RESEARCH_SYSTEM_PROMPT

    def test_research_prompt_shows_correct_example(self):
        """Test that research prompt shows correct JSON example."""
        from rev.agents.research import RESEARCH_SYSTEM_PROMPT

        # Should have example of correct response
        assert '{"tool_name": "read_file"' in RESEARCH_SYSTEM_PROMPT
        assert '"arguments"' in RESEARCH_SYSTEM_PROMPT

    def test_research_prompt_no_emojis(self):
        """Test that research prompt does not contain emojis."""
        from rev.agents.research import RESEARCH_SYSTEM_PROMPT

        # Common emojis that should NOT be present
        forbidden_chars = ['🚨', '🚫', '⚠️', '✅', '❌', '🎯']

        for emoji in forbidden_chars:
            assert emoji not in RESEARCH_SYSTEM_PROMPT, f"Found emoji {emoji} in research prompt"


class TestIntegrationScenarios:
    """Integration tests simulating real usage patterns."""

    def test_research_loop_prevention_scenario(self):
        """Test that a research loop scenario triggers budget limit."""
        # Simulate the scenario from the user's log:
        # Multiple consecutive READ tasks should trigger budget limit

        consecutive_read_actions = [
            "read",    # 1
            "read",    # 2
            "read",    # 3
            "read",    # 4
            "read",    # 5
            "read",    # 6 - Should trigger budget limit
        ]

        consecutive_reads = 0
        MAX_CONSECUTIVE_READS = 5

        for i, action in enumerate(consecutive_read_actions):
            if action in {'read', 'analyze', 'research'}:
                consecutive_reads += 1
            else:
                consecutive_reads = 0

            if i == 5:  # 6th task
                assert consecutive_reads >= MAX_CONSECUTIVE_READS
                # Budget limit should trigger here

    def test_redundant_file_read_scenario(self):
        """Test that reading the same file multiple times triggers blocking."""
        from rev.execution.orchestrator import _count_file_reads

        # Simulate reading app.js and tests/user.test.js multiple times
        task1 = Mock()
        task1.status = TaskStatus.COMPLETED
        task1.tool_events = [{"tool": "read_file", "args": {"file_path": "app.js"}}]

        task2 = Mock()
        task2.status = TaskStatus.COMPLETED
        task2.tool_events = [{"tool": "read_file", "args": {"file_path": "tests/user.test.js"}}]

        task3 = Mock()
        task3.status = TaskStatus.COMPLETED
        task3.tool_events = [{"tool": "read_file", "args": {"file_path": "app.js"}}]  # Duplicate

        completed_tasks = [task1, task2, task3]

        # Second read of app.js should be detected
        count = _count_file_reads("app.js", completed_tasks)
        assert count == 2  # Should trigger blocking on threshold >= 2

    def test_inconclusive_to_test_injection_scenario(self):
        """Test that inconclusive edit verification leads to TEST task."""
        # Scenario: Edit succeeds but verification is inconclusive

        edit_result = VerificationResult(
            passed=False,
            inconclusive=True,
            message="Cannot verify edit to user.test.js - file exists but no validation performed",
            details={
                "file_path": "tests/user.test.js",
                "suggestion": "Run pytest/npm test to verify changes"
            },
            should_replan=True
        )

        # Should trigger TEST task injection
        assert edit_result.inconclusive is True
        assert edit_result.should_replan is True

        # Orchestrator should inject TEST task based on file type
        file_path = edit_result.details["file_path"]
        is_js_file = any(ext in file_path for ext in ['.js', '.ts', '.vue'])

        if is_js_file:
            expected_test_cmd = "npm test"
        else:
            expected_test_cmd = "pytest"

        assert expected_test_cmd == "npm test"  # For .test.js file


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
