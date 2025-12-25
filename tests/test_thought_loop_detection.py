import json

from rev.execution import executor as executor_mod
from rev.execution.executor import ExecutionContext
from rev.models.task import ExecutionPlan


def test_detect_thought_loop_repeats():
    ctx = ExecutionContext(ExecutionPlan([]))
    first = ctx.detect_thought_loop(
        "I'm now reviewing the code structure to decide on the next step."
    )
    second = ctx.detect_thought_loop(
        "I'm now reviewing the code structure to decide on the next step."
    )
    assert first is None
    assert second is not None


def test_handle_thought_loop_tree_view_fallback(monkeypatch):
    ctx = ExecutionContext(ExecutionPlan([]))
    messages = []
    calls = {}

    def fake_execute_tool(name, args, agent_name=None):
        calls["name"] = name
        calls["args"] = args
        return json.dumps({"entries": []})

    monkeypatch.setattr(executor_mod, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(executor_mod, "_tool_message_content", lambda *args, **kwargs: "tool")

    handled = executor_mod._handle_thought_loop(
        "repeated response",
        "read",
        messages,
        ctx,
        debug_logger=None,
    )

    assert handled is True
    assert calls["name"] == "tree_view"
    assert messages[-1]["role"] == "tool"
    assert len(ctx.tool_call_history) == 1


def test_handle_thought_loop_prompts_on_edit():
    ctx = ExecutionContext(ExecutionPlan([]))
    messages = []

    handled = executor_mod._handle_thought_loop(
        "repeated response",
        "edit",
        messages,
        ctx,
        debug_logger=None,
    )

    assert handled is True
    assert messages[-1]["role"] == "user"
