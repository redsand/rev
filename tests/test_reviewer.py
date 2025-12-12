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
    assert len(calls) == 1
    assert review.decision == reviewer.ReviewDecision.APPROVED_WITH_SUGGESTIONS
    assert review.suggestions

