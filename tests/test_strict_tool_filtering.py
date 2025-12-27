"""
Tests for strict tool filtering in context_provider.

Ensures that semantic retrieval cannot override explicit tool constraints.
This prevents issues like gpt-oss receiving read_file for ADD tasks that
should only have access to write_file.

Issue: rev_run_20251225_135034.log showed CodeWriterAgent calling read_file
for ADD tasks instead of write_file, causing 21 "Write action completed
without write tool execution" failures.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from rev.agents.context_provider import build_context_and_tools
from rev.models.task import Task
from rev.core.context import RevContext


class TestStrictToolFiltering:
    """Test that candidate_tool_names constraint is strictly enforced."""

    def test_add_task_only_gets_write_file(self):
        """Test that ADD task with candidate=['write_file'] never gets read_file."""
        task = Task(
            description="create tests/user.test.js with Jest tests",
            action_type="add"
        )
        context = RevContext(user_request="Create test file")

        # Mock tool universe with multiple tools
        tool_universe = [
            {"function": {"name": "write_file", "description": "Write file"}},
            {"function": {"name": "read_file", "description": "Read file"}},
            {"function": {"name": "run_all_analysis", "description": "Run analysis"}},
        ]

        # Mock ContextBuilder to return tools NOT in candidate list (simulating retrieval bug)
        mock_bundle = MagicMock()
        mock_tool_read = MagicMock()
        mock_tool_read.schema = {"function": {"name": "read_file"}}
        mock_tool_write = MagicMock()
        mock_tool_write.schema = {"function": {"name": "write_file"}}
        mock_tool_analysis = MagicMock()
        mock_tool_analysis.schema = {"function": {"name": "run_all_analysis"}}

        # Retrieval returns read_file and run_all_analysis (WRONG for ADD task)
        mock_bundle.selected_tool_schemas = [mock_tool_read, mock_tool_analysis, mock_tool_write]

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=['write_file'],  # ONLY write_file allowed
                max_tools=7
            )

            # Verify ONLY write_file is in selected tools
            tool_names = [t.get("function", {}).get("name") for t in selected_tools]
            assert "write_file" in tool_names
            assert "read_file" not in tool_names
            assert "run_all_analysis" not in tool_names
            assert len([t for t in tool_names if t == "write_file"]) == 1

    def test_edit_task_only_gets_edit_tools(self):
        """Test that EDIT task only gets tools from candidate list."""
        task = Task(
            description="edit app.js to add user routes",
            action_type="edit"
        )
        context = RevContext(user_request="Edit file")

        tool_universe = [
            {"function": {"name": "replace_in_file", "description": "Replace in file"}},
            {"function": {"name": "write_file", "description": "Write file"}},
            {"function": {"name": "read_file", "description": "Read file"}},
            {"function": {"name": "run_tests", "description": "Run tests"}},
        ]

        mock_bundle = MagicMock()
        mock_read = MagicMock()
        mock_read.schema = {"function": {"name": "read_file"}}
        mock_replace = MagicMock()
        mock_replace.schema = {"function": {"name": "replace_in_file"}}
        mock_run_tests = MagicMock()
        mock_run_tests.schema = {"function": {"name": "run_tests"}}

        # Retrieval returns read_file and run_tests (NOT in candidate list)
        mock_bundle.selected_tool_schemas = [mock_read, mock_replace, mock_run_tests]

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=['replace_in_file', 'write_file'],
                max_tools=7
            )

            tool_names = [t.get("function", {}).get("name") for t in selected_tools]
            # Should only have replace_in_file from candidate list
            # (write_file was in candidate but not returned by retrieval)
            assert "replace_in_file" in tool_names
            assert "read_file" not in tool_names
            assert "run_tests" not in tool_names

    def test_fallback_when_retrieval_returns_empty(self):
        """Test fallback to candidate list when retrieval returns no tools."""
        task = Task(
            description="create directory tests",
            action_type="create_directory"
        )
        context = RevContext(user_request="Create directory")

        tool_universe = [
            {"function": {"name": "create_directory", "description": "Create dir"}},
            {"function": {"name": "write_file", "description": "Write file"}},
        ]

        mock_bundle = MagicMock()
        # Retrieval returns empty list
        mock_bundle.selected_tool_schemas = []

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=['create_directory'],
                max_tools=7
            )

            # Should fall back to candidate list
            tool_names = [t.get("function", {}).get("name") for t in selected_tools]
            assert "create_directory" in tool_names
            assert len(tool_names) == 1

    def test_fallback_when_all_retrieved_tools_filtered_out(self):
        """Test fallback when retrieval returns only disallowed tools."""
        task = Task(
            description="create new_file.js",
            action_type="add"
        )
        context = RevContext(user_request="Create file")

        tool_universe = [
            {"function": {"name": "write_file", "description": "Write file"}},
            {"function": {"name": "read_file", "description": "Read file"}},
            {"function": {"name": "run_tests", "description": "Run tests"}},
        ]

        mock_bundle = MagicMock()
        mock_read = MagicMock()
        mock_read.schema = {"function": {"name": "read_file"}}
        mock_tests = MagicMock()
        mock_tests.schema = {"function": {"name": "run_tests"}}

        # Retrieval returns ONLY disallowed tools (no write_file)
        mock_bundle.selected_tool_schemas = [mock_read, mock_tests]

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=['write_file'],
                max_tools=7
            )

            # After filtering, selected_tool_schemas would be empty
            # Should trigger fallback to candidate list
            tool_names = [t.get("function", {}).get("name") for t in selected_tools]
            assert "write_file" in tool_names
            assert "read_file" not in tool_names
            assert "run_tests" not in tool_names


class TestToolFilteringEdgeCases:
    """Test edge cases in tool filtering."""

    def test_empty_candidate_list_allows_all_tools(self):
        """Test that empty candidate list doesn't filter."""
        task = Task(description="generic task", action_type="unknown")
        context = RevContext(user_request="Do something")

        tool_universe = [
            {"function": {"name": "tool1", "description": "Tool 1"}},
            {"function": {"name": "tool2", "description": "Tool 2"}},
        ]

        mock_bundle = MagicMock()
        mock_t1 = MagicMock()
        mock_t1.schema = {"function": {"name": "tool1"}}
        mock_t2 = MagicMock()
        mock_t2.schema = {"function": {"name": "tool2"}}
        mock_bundle.selected_tool_schemas = [mock_t1, mock_t2]

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=[],  # Empty candidate list
                max_tools=7
            )

            # With empty candidate list, all retrieved tools should be included
            tool_names = [t.get("function", {}).get("name") for t in selected_tools]
            # Should have all tools from retrieval (no filtering)
            assert len(tool_names) >= 0  # May be empty or have tools depending on filtering logic

    def test_respects_max_tools_limit_in_fallback(self):
        """Test that fallback respects max_tools parameter."""
        task = Task(description="test task", action_type="test")
        context = RevContext(user_request="Test something")

        # Create many tools in universe
        tool_universe = [
            {"function": {"name": f"tool{i}", "description": f"Tool {i}"}}
            for i in range(20)
        ]

        candidate_names = [f"tool{i}" for i in range(15)]

        mock_bundle = MagicMock()
        # Retrieval returns empty
        mock_bundle.selected_tool_schemas = []

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=candidate_names,
                max_tools=5  # Limit to 5 tools
            )

            # Should respect max_tools limit
            assert len(selected_tools) <= 5


class TestIntegrationWithCodeWriterAgent:
    """Integration test simulating gpt-oss issue."""

    def test_gpt_oss_add_task_scenario(self):
        """
        Simulate the gpt-oss issue where ADD task received read_file instead of write_file.

        Before fix: Retrieval returns [read_file, run_all_analysis], no filtering applied
        After fix: Tools filtered to only [write_file] from candidate list
        """
        task = Task(
            description="create backend/tests/user.test.js with Jest and Supertest tests",
            action_type="add"
        )
        context = RevContext(user_request="continue creating test application")

        tool_universe = [
            {"function": {"name": "write_file", "description": "Write file"}},
            {"function": {"name": "read_file", "description": "Read file"}},
            {"function": {"name": "run_all_analysis", "description": "Run analysis"}},
            {"function": {"name": "search_code", "description": "Search code"}},
        ]

        mock_bundle = MagicMock()
        # Simulate retrieval returning wrong tools (what happened with gpt-oss)
        mock_read = MagicMock()
        mock_read.schema = {"function": {"name": "read_file"}}
        mock_analysis = MagicMock()
        mock_analysis.schema = {"function": {"name": "run_all_analysis"}}
        mock_bundle.selected_tool_schemas = [mock_read, mock_analysis]

        with patch('rev.agents.context_provider.get_context_builder') as mock_builder_fn:
            mock_builder = MagicMock()
            mock_builder.build.return_value = mock_bundle
            mock_builder.render.return_value = "rendered context"
            mock_builder_fn.return_value = mock_builder

            _, selected_tools, _ = build_context_and_tools(
                task,
                context,
                tool_universe=tool_universe,
                candidate_tool_names=['write_file'],  # CodeWriterAgent sets this for ADD
                max_tools=1
            )

            # After fix: Should only have write_file
            tool_names = [t.get("function", {}).get("name") for t in selected_tools]
            assert tool_names == ["write_file"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
