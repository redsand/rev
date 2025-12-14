from rev.execution import reviewer
from rev.models.task import ExecutionPlan


class DummyResponse:
    def __init__(self, content: str):
        self.content = content


def test_review_plan_falls_back_to_freeform(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("do a thing")

    def fake_chat(messages, tools=None):
        return {"message": {"content": "Review notes\n- item one\n- item two"}}

    monkeypatch.setattr(reviewer, "ollama_chat", fake_chat)

    review = reviewer.review_execution_plan(
        plan,
        user_request="test request",
        auto_approve_low_risk=False,
        max_parse_retries=0,
    )

    assert review.decision == reviewer.ReviewDecision.APPROVED_WITH_SUGGESTIONS
    assert review.suggestions == ["item one", "item two"]
    assert "Review notes" in review.overall_assessment


def test_review_plan_handles_non_json_on_retry(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("another task")

    calls = []

    def fake_chat(messages, tools=None):
        calls.append(True)
        return {"message": {"content": "No JSON here"}}

    monkeypatch.setattr(reviewer, "ollama_chat", fake_chat)

    review = reviewer.review_execution_plan(
        plan,
        user_request="test request",
        auto_approve_low_risk=False,
        max_parse_retries=1,
    )

    # Should still fall back without raising after the initial attempt
    assert len(calls) == 2
    assert review.decision == reviewer.ReviewDecision.APPROVED_WITH_SUGGESTIONS
    assert review.suggestions


def test_review_plan_parses_embedded_json(monkeypatch):
    plan = ExecutionPlan()
    plan.add_task("context gathering")

    content = (
        "Brief note from the assistant.\n"
        "{"
        '"decision": "requires_changes",'
        '"overall_assessment": "Need more detail",'
        '"confidence_score": 0.92,'
        '"issues": [{"severity": "high", "task_id": 0, "description": "Missing steps", "impact": "task incomplete"}],'
        '"suggestions": ["Add a focused plan"],'
        '"security_concerns": ["None"],'
        '"missing_tasks": ["Add implementation steps"],'
        '"unnecessary_tasks": []'
        "}\n"
        "End of review"
    )

    monkeypatch.setattr(
        reviewer,
        "ollama_chat",
        lambda messages, tools=None: {"message": {"content": content}},
    )

    review = reviewer.review_execution_plan(
        plan,
        user_request="review the code structure",
        auto_approve_low_risk=False,
        max_parse_retries=0,
    )

    assert review.decision == reviewer.ReviewDecision.REQUIRES_CHANGES
    assert review.overall_assessment == "Need more detail"
    assert review.issues and review.issues[0]["description"] == "Missing steps"
    assert review.missing_tasks == ["Add implementation steps"]


def test_review_action_parses_embedded_json(monkeypatch):
    def fake_chat(messages, tools=None):
        return {
            "message": {
                "content": '\nResponse header\n{"approved": false, "recommendation": "Re-evaluate", "concerns": ["check inputs"], "security_warnings": [], "alternative_approaches": ["retry later"]}\nFooter'
            }
        }

    monkeypatch.setattr(reviewer, "ollama_chat", fake_chat)

    action_review = reviewer.review_action(
        action_type="run_cmd",
        action_description="Run a command",
        tool_name="run_cmd",
        tool_args={"cmd": "echo hi"},
    )

    assert not action_review.approved
    assert action_review.recommendation == "Re-evaluate"
    assert action_review.concerns == ["check inputs"]
