import json

from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.core.tool_call_recovery import RecoveredToolCall
from rev.agents.research import ResearchAgent
from rev.models.task import Task
from rev.core.context import RevContext
import rev.core.tool_call_retry as retry_mod
import rev.agents.research as research_mod


def test_retry_tool_call_parses_json_content(monkeypatch):
    captured = {}

    def fake_chat(messages, tools=None, model=None, supports_tools=None, **kwargs):
        captured["kwargs"] = kwargs
        return {"message": {"content": "{\"tool_name\":\"list_dir\",\"arguments\":{\"pattern\":\"src/**\"}}"}}

    monkeypatch.setattr(retry_mod, "ollama_chat", fake_chat)

    recovered = retry_tool_call_with_response_format(
        [{"role": "user", "content": "List files"}],
        [{"function": {"name": "list_dir"}}],
        allowed_tools=["list_dir"],
    )

    assert recovered is not None
    assert recovered.name == "list_dir"
    assert recovered.arguments == {"pattern": "src/**"}
    assert captured["kwargs"]["response_format"] == {"type": "json_object"}
    assert captured["kwargs"]["format"] == "json"


def test_retry_tool_call_parses_tool_calls(monkeypatch):
    def fake_chat(messages, tools=None, model=None, supports_tools=None, **kwargs):
        return {
            "message": {
                "tool_calls": [
                    {"function": {"name": "list_dir", "arguments": "{\"pattern\":\"src/**\"}"}}
                ]
            }
        }

    monkeypatch.setattr(retry_mod, "ollama_chat", fake_chat)

    recovered = retry_tool_call_with_response_format(
        [{"role": "user", "content": "List files"}],
        [{"function": {"name": "list_dir"}}],
        allowed_tools=["list_dir"],
    )

    assert recovered is not None
    assert recovered.name == "list_dir"
    assert recovered.arguments == {"pattern": "src/**"}


def test_research_agent_uses_retry_before_text_recovery(monkeypatch):
    calls = {"retry": 0, "tool": 0}

    def fake_chat(messages, tools=None, model=None, supports_tools=None, **kwargs):
        return {"message": {"content": "Use list_dir"}}

    def fake_retry(messages, tools, allowed_tools=None, model=None, supports_tools=True):
        calls["retry"] += 1
        return RecoveredToolCall(name="list_dir", arguments={"pattern": "src/**"})

    def fake_execute_tool(name, args, agent_name=None):
        calls["tool"] += 1
        return json.dumps({"files": []})

    def fake_build_output(**kwargs):
        return json.dumps({"tool_name": kwargs["tool_name"]})

    monkeypatch.setattr(research_mod, "ollama_chat", fake_chat)
    monkeypatch.setattr(research_mod, "retry_tool_call_with_response_format", fake_retry)
    monkeypatch.setattr(research_mod, "recover_tool_call_from_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("text recovery should not be used")))
    monkeypatch.setattr(research_mod, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(research_mod, "build_subagent_output", fake_build_output)
    monkeypatch.setattr(research_mod, "get_available_tools", lambda: [{"function": {"name": "list_dir"}}])
    monkeypatch.setattr(research_mod, "build_context_and_tools", lambda *args, **kwargs: ("", [{"function": {"name": "list_dir"}}], None))

    context = RevContext(user_request="list files")
    task = Task("List files", action_type="read")
    task.task_id = 0

    agent = ResearchAgent()
    result = agent.execute(task, context)

    assert calls["retry"] == 1
    assert calls["tool"] == 1
    payload = json.loads(result)
    assert payload["tool_name"] == "list_dir"
