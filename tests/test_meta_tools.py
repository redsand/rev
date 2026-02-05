"""Tests for ToolExecutorAgent meta-tool coordination feature.

Meta-tools (request_replanning, request_research, request_user_guidance,
inject_tasks, escalate_strategy, add_insight) allow the LLM inside
ToolExecutorAgent to trigger agent coordination mechanisms instead of
failing with "unknown_tool" errors.

Tests cover:
  - _is_meta_tool identification
  - Each meta-tool handler via direct call
  - CLI-style invocation interception
  - LLM tool_calls API interception
  - Text-recovery path interception
  - Registry presence of meta-tool definitions and dispatch entries
"""

import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from rev.agents.tool_executor import ToolExecutorAgent, _parse_cli_style_invocation
from rev.core.context import RevContext
from rev.models.task import Task
from rev.tools.registry import get_available_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    return ToolExecutorAgent()


@pytest.fixture
def context():
    return RevContext(user_request="test meta-tools")


@pytest.fixture
def task():
    t = Task(description="placeholder", action_type="tool")
    t.task_id = "test-1"
    return t


# Patch targets scoped to the tool_executor module
_PATCH_PREFIX = "rev.agents.tool_executor"


def _mock_llm_tool_call(tool_name: str, arguments: dict):
    """Build a mock ollama_chat response with a single tool call."""
    return {
        "message": {
            "tool_calls": [
                {
                    "function": {
                        "name": tool_name,
                        "arguments": arguments,
                    }
                }
            ]
        }
    }


def _recovered(name: str, arguments: dict):
    """Create a SimpleNamespace mimicking a recovered tool call."""
    return SimpleNamespace(name=name, arguments=arguments)


# ---------------------------------------------------------------------------
# 1. _is_meta_tool identification
# ---------------------------------------------------------------------------

class TestIsMetaTool:
    """Verify _is_meta_tool correctly classifies tool names."""

    @pytest.mark.parametrize("name", [
        "request_replanning",
        "request_research",
        "request_user_guidance",
        "inject_tasks",
        "escalate_strategy",
        "add_insight",
    ])
    def test_recognises_meta_tools(self, agent, name):
        assert agent._is_meta_tool(name) is True

    @pytest.mark.parametrize("name", [
        "read_file",
        "write_file",
        "run_cmd",
        "git_diff",
        "request_replan",       # close but not a meta-tool name
        "replanning",
        "",
    ])
    def test_rejects_non_meta_tools(self, agent, name):
        assert agent._is_meta_tool(name) is False


# ---------------------------------------------------------------------------
# 2. Individual handler unit tests (direct call, no LLM needed)
# ---------------------------------------------------------------------------

class TestHandleReplanning:
    def test_adds_replan_request_to_context(self, agent, context):
        result = agent._handle_replanning(context, {
            "reason": "missing dependency",
            "suggestion": "use CREATE_TOOL",
        })
        assert "[RECOVERY_REQUESTED]" in result
        assert "replanning_requested" in result
        reqs = [r for r in context.agent_requests if r["type"] == "REPLAN_REQUEST"]
        assert len(reqs) == 1
        assert "missing dependency" in reqs[0]["details"]["detailed_reason"]
        assert "CREATE_TOOL" in reqs[0]["details"]["detailed_reason"]

    def test_defaults_when_args_empty(self, agent, context):
        result = agent._handle_replanning(context, {})
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "REPLAN_REQUEST"]
        assert len(reqs) == 1
        assert "LLM requested replanning" in reqs[0]["details"]["reason"]


class TestHandleResearch:
    def test_adds_research_request(self, agent, context):
        result = agent._handle_research(context, {
            "query": "find auth middleware",
            "reason": "need to understand auth flow",
        })
        assert "[RECOVERY_REQUESTED]" in result
        assert "research_requested" in result
        reqs = [r for r in context.agent_requests if r["type"] == "RESEARCH_REQUEST"]
        assert len(reqs) == 1
        assert reqs[0]["details"]["query"] == "find auth middleware"

    def test_defaults_when_args_empty(self, agent, context):
        result = agent._handle_research(context, {})
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "RESEARCH_REQUEST"]
        assert len(reqs) == 1


class TestHandleUserGuidance:
    def test_adds_user_guidance_request(self, agent, context):
        result = agent._handle_user_guidance(context, {
            "question": "Which DB driver?",
            "options": ["postgres", "mysql", "sqlite"],
        })
        assert "[RECOVERY_REQUESTED]" in result
        assert "user_guidance_requested" in result
        reqs = [r for r in context.agent_requests if r["type"] == "USER_GUIDANCE"]
        assert len(reqs) == 1
        assert reqs[0]["details"]["agent"] == "ToolExecutorAgent"
        assert "Which DB driver?" in reqs[0]["details"]["reason"]
        assert "postgres" in reqs[0]["details"]["guidance"]

    def test_no_options(self, agent, context):
        result = agent._handle_user_guidance(context, {
            "question": "What should I do?",
        })
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "USER_GUIDANCE"]
        assert len(reqs) == 1
        assert "Options:" not in reqs[0]["details"]["guidance"]


class TestHandleInjectTasks:
    def test_injects_tasks_into_context(self, agent, context):
        tasks_to_inject = [
            {"description": "install phpunit", "action_type": "tool"},
            {"description": "configure test runner", "action_type": "tool", "priority": "high"},
        ]
        result = agent._handle_inject_tasks(context, {
            "tasks": tasks_to_inject,
            "reason": "dependencies missing",
        })
        assert "[RECOVERY_REQUESTED]" in result
        assert "tasks_injected" in result
        reqs = [r for r in context.agent_requests if r["type"] == "INJECT_TASKS"]
        assert len(reqs) == 1
        assert len(reqs[0]["details"]["tasks"]) == 2
        assert reqs[0]["details"]["tasks"][0]["description"] == "install phpunit"

    def test_empty_tasks(self, agent, context):
        result = agent._handle_inject_tasks(context, {"tasks": []})
        assert "[RECOVERY_REQUESTED]" in result
        assert "Injected 0 task(s)" in result


class TestHandleEscalateStrategy:
    def test_adds_escalation_request(self, agent, context):
        result = agent._handle_escalate_strategy(context, {
            "reason": "replace_in_file keeps failing",
            "suggestion": "use write_file to rewrite entire file",
        })
        assert "[RECOVERY_REQUESTED]" in result
        assert "strategy_escalated" in result
        reqs = [r for r in context.agent_requests if r["type"] == "EDIT_STRATEGY_ESCALATION"]
        assert len(reqs) == 1
        assert "replace_in_file" in reqs[0]["details"]["reason"]
        assert "write_file" in reqs[0]["details"]["detailed_reason"]

    def test_no_suggestion(self, agent, context):
        result = agent._handle_escalate_strategy(context, {
            "reason": "current approach fails",
        })
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "EDIT_STRATEGY_ESCALATION"]
        assert len(reqs) == 1


class TestHandleAddInsight:
    def test_stores_insight_in_context(self, agent, context):
        result = agent._handle_add_insight(context, {
            "key": "test_framework",
            "value": "project uses phpunit 9.x",
        })
        assert "Insight recorded" in result
        assert "test_framework" in result
        assert context.agent_insights["ToolExecutorAgent"]["test_framework"] == "project uses phpunit 9.x"

    def test_defaults(self, agent, context):
        result = agent._handle_add_insight(context, {})
        assert "Insight recorded" in result
        assert context.agent_insights["ToolExecutorAgent"]["unknown"] == ""


# ---------------------------------------------------------------------------
# 3. _handle_meta_tool dispatcher
# ---------------------------------------------------------------------------

class TestHandleMetaToolDispatch:
    def test_dispatches_to_correct_handler(self, agent, context):
        """Each meta-tool name is dispatched to the right handler."""
        result = agent._handle_meta_tool(context, "request_replanning", {"reason": "test"})
        assert "[RECOVERY_REQUESTED]" in result
        assert any(r["type"] == "REPLAN_REQUEST" for r in context.agent_requests)

    def test_unknown_meta_tool_fails(self, agent, context):
        result = agent._handle_meta_tool(context, "nonexistent_meta", {})
        assert "[FINAL_FAILURE]" in result
        assert "unknown_meta_tool" in result


# ---------------------------------------------------------------------------
# 4. CLI-style invocation path
# ---------------------------------------------------------------------------

class TestCLIStyleMetaTool:
    """When the task description is a CLI-style invocation of a meta-tool."""

    @pytest.mark.parametrize("meta_name,args_str,expected_request_type", [
        ("request_replanning", '--reason "need different approach"', "REPLAN_REQUEST"),
        ("request_research", '--query "find test config"', "RESEARCH_REQUEST"),
        ("request_user_guidance", '--question "which env?"', "USER_GUIDANCE"),
        ("escalate_strategy", '--reason "edits keep failing"', "EDIT_STRATEGY_ESCALATION"),
    ])
    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    def test_cli_meta_tool_intercepted(
        self, mock_chat, mock_bct, mock_tools,
        agent, context, task,
        meta_name, args_str, expected_request_type,
    ):
        # Setup: task description is a CLI-style meta-tool invocation
        task.description = f"{meta_name} {args_str}"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}},
        ]

        result = agent.execute(task, context)

        # Meta-tool was handled; LLM should never be called
        mock_chat.assert_not_called()
        assert "[RECOVERY_REQUESTED]" in result
        assert any(r["type"] == expected_request_type for r in context.agent_requests)

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    def test_cli_inject_tasks(self, mock_chat, mock_bct, mock_tools, agent, context, task):
        task.description = 'inject_tasks --reason "missing step"'
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}},
        ]

        result = agent.execute(task, context)

        mock_chat.assert_not_called()
        assert "[RECOVERY_REQUESTED]" in result
        assert any(r["type"] == "INJECT_TASKS" for r in context.agent_requests)

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    def test_cli_add_insight(self, mock_chat, mock_bct, mock_tools, agent, context, task):
        task.description = 'add_insight --key "lang" --value "php"'
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}},
        ]

        result = agent.execute(task, context)

        mock_chat.assert_not_called()
        assert "Insight recorded" in result


# ---------------------------------------------------------------------------
# 5. LLM tool_calls API path
# ---------------------------------------------------------------------------

class TestLLMToolCallsMetaTool:
    """When the LLM responds with a tool_call for a meta-tool."""

    @pytest.mark.parametrize("meta_name,meta_args,expected_request_type", [
        (
            "request_replanning",
            {"reason": "tool not found", "suggestion": "use CREATE_TOOL"},
            "REPLAN_REQUEST",
        ),
        (
            "request_research",
            {"query": "how is auth done?", "reason": "need context"},
            "RESEARCH_REQUEST",
        ),
        (
            "request_user_guidance",
            {"question": "Pick a framework", "options": ["django", "flask"]},
            "USER_GUIDANCE",
        ),
        (
            "inject_tasks",
            {"tasks": [{"description": "install deps"}], "reason": "missing"},
            "INJECT_TASKS",
        ),
        (
            "escalate_strategy",
            {"reason": "patch format unsupported", "suggestion": "write whole file"},
            "EDIT_STRATEGY_ESCALATION",
        ),
    ])
    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    def test_llm_meta_tool_intercepted(
        self, mock_exec, mock_chat, mock_bct, mock_tools,
        agent, context, task,
        meta_name, meta_args, expected_request_type,
    ):
        # Task description does NOT parse as CLI-style (starts with a brace-free sentence)
        task.description = "Run some shell command that the LLM decides needs replanning"

        mock_tools.return_value = [
            {"type": "function", "function": {"name": "run_cmd", "description": "run", "parameters": {}}},
        ]
        mock_bct.return_value = ("rendered context", [{"type": "function", "function": {"name": "run_cmd"}}], None)
        mock_chat.return_value = _mock_llm_tool_call(meta_name, meta_args)

        result = agent.execute(task, context)

        # execute_tool should NOT be called for meta-tools
        mock_exec.assert_not_called()
        assert "[RECOVERY_REQUESTED]" in result
        assert any(r["type"] == expected_request_type for r in context.agent_requests)

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    def test_llm_add_insight_returns_directly(
        self, mock_exec, mock_chat, mock_bct, mock_tools,
        agent, context, task,
    ):
        task.description = "Analyze the codebase"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "search_code", "description": "search", "parameters": {}}},
        ]
        mock_bct.return_value = ("ctx", [], None)
        mock_chat.return_value = _mock_llm_tool_call("add_insight", {
            "key": "framework",
            "value": "laravel",
        })

        result = agent.execute(task, context)

        mock_exec.assert_not_called()
        assert "Insight recorded" in result
        assert context.agent_insights["ToolExecutorAgent"]["framework"] == "laravel"

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    def test_llm_meta_tool_with_string_arguments(
        self, mock_exec, mock_chat, mock_bct, mock_tools,
        agent, context, task,
    ):
        """Arguments come as JSON string (not dict) from some LLM providers."""
        task.description = "Do something"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "run_cmd", "description": "run", "parameters": {}}},
        ]
        mock_bct.return_value = ("ctx", [], None)
        mock_chat.return_value = {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "request_replanning",
                            "arguments": json.dumps({"reason": "wrong tool"}),
                        }
                    }
                ]
            }
        }

        result = agent.execute(task, context)

        mock_exec.assert_not_called()
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "REPLAN_REQUEST"]
        assert len(reqs) == 1


# ---------------------------------------------------------------------------
# 6. Text-recovery path interception
# ---------------------------------------------------------------------------

class TestRecoveryPathMetaTool:
    """When meta-tools are recovered from text output (no tool_calls in response)."""

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    @patch(f"{_PATCH_PREFIX}.recover_tool_call_from_text")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    def test_first_recovery_intercepts_meta_tool(
        self, mock_exec, mock_recover, mock_chat, mock_bct, mock_tools,
        agent, context, task,
    ):
        """recover_tool_call_from_text returns a meta-tool; should be intercepted."""
        task.description = "Do something"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "run_cmd", "description": "run", "parameters": {}}},
        ]
        mock_bct.return_value = ("ctx", [], None)
        # LLM returns text without tool_calls
        mock_chat.return_value = {"message": {"content": "I need to replan"}}
        # Recovery parses the text and finds a meta-tool
        mock_recover.return_value = _recovered("request_replanning", {"reason": "can't proceed"})

        result = agent.execute(task, context)

        mock_exec.assert_not_called()
        assert "[RECOVERY_REQUESTED]" in result
        assert any(r["type"] == "REPLAN_REQUEST" for r in context.agent_requests)

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    @patch(f"{_PATCH_PREFIX}.recover_tool_call_from_text")
    @patch(f"{_PATCH_PREFIX}.recover_tool_call_from_text_lenient")
    @patch(f"{_PATCH_PREFIX}.retry_tool_call_with_response_format")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    def test_retry_recovery_intercepts_meta_tool(
        self, mock_exec, mock_retry, mock_lenient, mock_recover,
        mock_chat, mock_bct, mock_tools,
        agent, context, task,
    ):
        """retry_tool_call_with_response_format returns a meta-tool; should be intercepted."""
        task.description = "Do something"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "run_cmd", "description": "run", "parameters": {}}},
        ]
        mock_bct.return_value = ("ctx", [], None)
        mock_chat.return_value = {"message": {"content": "need research"}}
        # First two recoveries fail
        mock_recover.return_value = None
        mock_lenient.return_value = None
        # Retry with response_format finds a meta-tool
        mock_retry.return_value = _recovered("request_research", {"query": "find tests"})

        result = agent.execute(task, context)

        mock_exec.assert_not_called()
        assert "[RECOVERY_REQUESTED]" in result
        assert any(r["type"] == "RESEARCH_REQUEST" for r in context.agent_requests)


# ---------------------------------------------------------------------------
# 7. Normal tools are NOT intercepted as meta-tools
# ---------------------------------------------------------------------------

class TestNormalToolNotIntercepted:
    """Regular tools should bypass meta-tool handling and execute normally."""

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    @patch(f"{_PATCH_PREFIX}.build_subagent_output")
    def test_cli_normal_tool_executes(
        self, mock_output, mock_exec, mock_tools,
        agent, context, task,
    ):
        task.description = "read_file --path /tmp/test.txt"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}},
        ]
        mock_exec.return_value = '{"content": "hello"}'
        mock_output.return_value = "output"

        result = agent.execute(task, context)

        mock_exec.assert_called_once_with("read_file", {"path": "/tmp/test.txt"}, agent_name="ToolExecutorAgent")
        assert result == "output"
        # No agent requests should have been added
        assert len(context.agent_requests) == 0

    @patch(f"{_PATCH_PREFIX}.get_available_tools")
    @patch(f"{_PATCH_PREFIX}.build_context_and_tools")
    @patch(f"{_PATCH_PREFIX}.ollama_chat")
    @patch(f"{_PATCH_PREFIX}.execute_tool")
    @patch(f"{_PATCH_PREFIX}.build_subagent_output")
    def test_llm_normal_tool_executes(
        self, mock_output, mock_exec, mock_chat, mock_bct, mock_tools,
        agent, context, task,
    ):
        task.description = "Read the config file"
        mock_tools.return_value = [
            {"type": "function", "function": {"name": "read_file", "description": "read", "parameters": {}}},
        ]
        mock_bct.return_value = ("ctx", [], None)
        mock_chat.return_value = _mock_llm_tool_call("read_file", {"path": "/etc/config"})
        mock_exec.return_value = '{"content": "data"}'
        mock_output.return_value = "output"

        result = agent.execute(task, context)

        mock_exec.assert_called_once()
        assert result == "output"
        assert len(context.agent_requests) == 0


# ---------------------------------------------------------------------------
# 8. Registry presence
# ---------------------------------------------------------------------------

class TestRegistryPresence:
    """Meta-tools should be present in the tool registry."""

    META_TOOL_NAMES = {
        "request_replanning",
        "request_research",
        "request_user_guidance",
        "inject_tasks",
        "escalate_strategy",
        "add_insight",
    }

    def test_meta_tools_in_available_tools(self):
        tools = get_available_tools()
        tool_names = {
            t.get("function", {}).get("name")
            for t in tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
        }
        for name in self.META_TOOL_NAMES:
            assert name in tool_names, f"Meta-tool '{name}' missing from get_available_tools()"

    def test_meta_tool_schemas_have_required_fields(self):
        tools = get_available_tools()
        meta_tools = {
            t["function"]["name"]: t
            for t in tools
            if isinstance(t, dict)
            and isinstance(t.get("function"), dict)
            and t["function"].get("name") in self.META_TOOL_NAMES
        }
        for name in self.META_TOOL_NAMES:
            assert name in meta_tools, f"Meta-tool '{name}' not found"
            func = meta_tools[name]["function"]
            assert "description" in func, f"Meta-tool '{name}' missing description"
            assert "parameters" in func, f"Meta-tool '{name}' missing parameters"
            assert func["parameters"].get("type") == "object", f"Meta-tool '{name}' params not object"

    def test_meta_tool_dispatch_entries_exist(self):
        """Meta-tools should have entries in _build_tool_dispatch."""
        from rev.tools.registry import _build_tool_dispatch
        dispatch = _build_tool_dispatch()
        for name in self.META_TOOL_NAMES:
            assert name in dispatch, f"Meta-tool '{name}' missing from dispatch table"

    def test_dispatch_entries_return_json(self):
        """Dispatch handlers should return valid JSON."""
        from rev.tools.registry import _build_tool_dispatch
        dispatch = _build_tool_dispatch()
        for name in self.META_TOOL_NAMES:
            handler = dispatch[name]
            result = handler({"reason": "test", "query": "test", "question": "test",
                              "key": "k", "value": "v", "suggestion": "s",
                              "tasks": [], "options": []})
            parsed = json.loads(result)
            assert "status" in parsed, f"Dispatch for '{name}' missing 'status' field"


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_meta_tool_with_none_args(self, agent, context):
        """Handler should not crash if args dict has None values."""
        result = agent._handle_replanning(context, {"reason": None, "suggestion": None})
        assert "[RECOVERY_REQUESTED]" in result

    def test_meta_tool_handler_with_extra_args(self, agent, context):
        """Extra unknown args should be silently ignored."""
        result = agent._handle_research(context, {
            "query": "find tests",
            "reason": "need context",
            "extra_field": "ignored",
        })
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "RESEARCH_REQUEST"]
        assert len(reqs) == 1

    def test_inject_tasks_with_non_dict_items(self, agent, context):
        """Non-dict items in tasks list should not crash the handler."""
        result = agent._handle_inject_tasks(context, {
            "tasks": [{"description": "valid"}, "invalid_string", 42],
        })
        assert "[RECOVERY_REQUESTED]" in result
        # Should only pick up the dict description
        assert "valid" in result

    def test_user_guidance_options_as_empty(self, agent, context):
        result = agent._handle_user_guidance(context, {
            "question": "what now?",
            "options": [],
        })
        assert "[RECOVERY_REQUESTED]" in result
        reqs = [r for r in context.agent_requests if r["type"] == "USER_GUIDANCE"]
        assert "Options:" not in reqs[0]["details"]["guidance"]

    def test_add_insight_overwrites_same_key(self, agent, context):
        """Calling add_insight twice with same key should update the value."""
        agent._handle_add_insight(context, {"key": "lang", "value": "python"})
        agent._handle_add_insight(context, {"key": "lang", "value": "php"})
        assert context.agent_insights["ToolExecutorAgent"]["lang"] == "php"


# ---------------------------------------------------------------------------
# 10. Parse CLI helper recognises meta-tool names
# ---------------------------------------------------------------------------

class TestParseCLIWithMetaTools:
    def test_parses_replanning(self):
        result = _parse_cli_style_invocation('request_replanning --reason "wrong tool"')
        assert result is not None
        name, args = result
        assert name == "request_replanning"
        assert "reason" in args

    def test_parses_inject_tasks(self):
        result = _parse_cli_style_invocation("inject_tasks --reason missing")
        assert result is not None
        name, args = result
        assert name == "inject_tasks"
        assert args["reason"] == "missing"

    def test_parses_add_insight(self):
        result = _parse_cli_style_invocation("add_insight --key lang --value php")
        assert result is not None
        name, args = result
        assert name == "add_insight"
        assert args["key"] == "lang"
        assert args["value"] == "php"
