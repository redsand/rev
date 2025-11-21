"""
Review agent for validating plans and actions.

This module provides the review phase functionality that validates execution plans
and individual actions, providing recommendations and identifying potential issues.
"""

import json
import re
from typing import Dict, Any, List, Optional
from enum import Enum

from rev.models.task import ExecutionPlan, Task, RiskLevel
from rev.llm.client import ollama_chat


class ReviewStrictness(Enum):
    """How strict the review should be."""
    LENIENT = "lenient"  # Only flag critical issues
    MODERATE = "moderate"  # Flag medium+ issues
    STRICT = "strict"  # Flag all potential issues


class ReviewDecision(Enum):
    """Review decision outcomes."""
    APPROVED = "approved"
    APPROVED_WITH_SUGGESTIONS = "approved_with_suggestions"
    REQUIRES_CHANGES = "requires_changes"
    REJECTED = "rejected"


class PlanReview:
    """Represents a review of an execution plan."""
    def __init__(self):
        self.decision = ReviewDecision.APPROVED
        self.issues: List[Dict[str, Any]] = []
        self.suggestions: List[str] = []
        self.security_concerns: List[str] = []
        self.missing_tasks: List[str] = []
        self.unnecessary_tasks: List[int] = []  # Task IDs
        self.improved_plan: Optional[ExecutionPlan] = None
        self.overall_assessment: str = ""
        self.confidence_score: float = 0.0  # 0.0 to 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "security_concerns": self.security_concerns,
            "missing_tasks": self.missing_tasks,
            "unnecessary_tasks": self.unnecessary_tasks,
            "overall_assessment": self.overall_assessment,
            "confidence_score": self.confidence_score
        }


class ActionReview:
    """Represents a review of a proposed action/tool call."""
    def __init__(self):
        self.approved = True
        self.concerns: List[str] = []
        self.alternative_approaches: List[str] = []
        self.security_warnings: List[str] = []
        self.recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "concerns": self.concerns,
            "alternative_approaches": self.alternative_approaches,
            "security_warnings": self.security_warnings,
            "recommendation": self.recommendation
        }


PLAN_REVIEW_SYSTEM = """You are an expert code review agent specializing in CI/CD workflows and software architecture.

Your job is to review execution plans and identify:
1. **Completeness**: Are all necessary tasks included?
2. **Correctness**: Do the tasks achieve the stated goal?
3. **Dependencies**: Are task dependencies correct and complete?
4. **Risk**: Are risks properly assessed and mitigated?
5. **Security**: Are there security vulnerabilities being introduced?
6. **Best Practices**: Does the plan follow best practices?
7. **Edge Cases**: Are edge cases and error handling considered?
8. **Performance**: Could the approach cause performance issues?
9. **Maintainability**: Will the changes be maintainable?
10. **Testing**: Is adequate testing included?

Analyze the plan critically but constructively. Identify real issues, not nitpicks.

Return your review in JSON format:
{
  "decision": "approved|approved_with_suggestions|requires_changes|rejected",
  "overall_assessment": "Brief summary of your assessment",
  "confidence_score": 0.85,
  "issues": [
    {
      "severity": "critical|high|medium|low",
      "task_id": 2,
      "description": "Issue description",
      "impact": "What could go wrong"
    }
  ],
  "suggestions": [
    "Specific improvement suggestion"
  ],
  "security_concerns": [
    "Security issue description"
  ],
  "missing_tasks": [
    "Description of task that should be added"
  ],
  "unnecessary_tasks": [1, 3]
}

Be thorough but practical. Focus on issues that could cause real problems."""


ACTION_REVIEW_SYSTEM = """You are an expert security and best practices review agent.

Your job is to review individual actions (tool calls, code changes) before execution.

Analyze each action for:
1. **Security**: SQL injection, XSS, command injection, exposed secrets, etc.
2. **Safety**: Data loss, destructive operations, breaking changes
3. **Correctness**: Logic errors, incorrect assumptions
4. **Best Practices**: Code quality, maintainability, performance
5. **Alternative Approaches**: Better ways to achieve the same goal

Return your review in JSON format:
{
  "approved": true,
  "recommendation": "Brief recommendation",
  "concerns": [
    "Specific concern about this action"
  ],
  "security_warnings": [
    "Security issue found"
  ],
  "alternative_approaches": [
    "Consider using X instead because..."
  ]
}

Be practical - don't block reasonable actions over minor style issues.
Focus on preventing real bugs, security issues, and architectural problems."""


def review_execution_plan(
    plan: ExecutionPlan,
    user_request: str,
    strictness: ReviewStrictness = ReviewStrictness.MODERATE,
    auto_approve_low_risk: bool = True
) -> PlanReview:
    """Review an execution plan and provide feedback.

    Args:
        plan: The execution plan to review
        user_request: The original user request
        strictness: How strict the review should be
        auto_approve_low_risk: Automatically approve plans with only low-risk tasks

    Returns:
        PlanReview with decision and feedback
    """
    print("\n" + "=" * 60)
    print("REVIEW AGENT - PLAN REVIEW")
    print("=" * 60)

    review = PlanReview()

    # Quick check: If all tasks are low risk, auto-approve if enabled
    if auto_approve_low_risk:
        all_low_risk = all(task.risk_level == RiskLevel.LOW for task in plan.tasks)
        if all_low_risk and len(plan.tasks) > 0:
            print("→ All tasks are low-risk. Auto-approving.")
            review.decision = ReviewDecision.APPROVED
            review.overall_assessment = "Plan approved: All tasks are low-risk."
            review.confidence_score = 0.95
            return review

    # Prepare plan summary for LLM
    plan_summary = {
        "user_request": user_request,
        "total_tasks": len(plan.tasks),
        "tasks": []
    }

    for i, task in enumerate(plan.tasks):
        task_info = {
            "task_id": i,
            "description": task.description,
            "action_type": task.action_type,
            "risk_level": task.risk_level.value,
            "dependencies": task.dependencies,
            "breaking_change": task.breaking_change
        }
        plan_summary["tasks"].append(task_info)

    # Get LLM review
    messages = [
        {"role": "system", "content": PLAN_REVIEW_SYSTEM},
        {"role": "user", "content": f"""Review this execution plan:

{json.dumps(plan_summary, indent=2)}

Strictness level: {strictness.value}

Provide a thorough review."""}
    ]

    print("→ Analyzing plan with review agent...")
    response = ollama_chat(messages)

    if "error" in response:
        print(f"⚠️  Review agent error: {response['error']}")
        # Default to approved with warning
        review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
        review.suggestions.append("Review agent unavailable - plan approved by default")
        review.confidence_score = 0.5
        return review

    # Parse review response
    try:
        content = response.get("message", {}).get("content", "")
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            review_data = json.loads(json_match.group(0))

            # Map decision
            decision_str = review_data.get("decision", "approved").lower()
            if "rejected" in decision_str:
                review.decision = ReviewDecision.REJECTED
            elif "requires_changes" in decision_str:
                review.decision = ReviewDecision.REQUIRES_CHANGES
            elif "suggestions" in decision_str:
                review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
            else:
                review.decision = ReviewDecision.APPROVED

            review.overall_assessment = review_data.get("overall_assessment", "")
            review.confidence_score = float(review_data.get("confidence_score", 0.8))
            review.issues = review_data.get("issues", [])
            review.suggestions = review_data.get("suggestions", [])
            review.security_concerns = review_data.get("security_concerns", [])
            review.missing_tasks = review_data.get("missing_tasks", [])
            review.unnecessary_tasks = review_data.get("unnecessary_tasks", [])

    except Exception as e:
        print(f"⚠️  Error parsing review: {e}")
        review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
        review.suggestions.append("Could not parse review - approved by default")
        review.confidence_score = 0.5

    # Display review
    _display_plan_review(review, plan)

    return review


def review_action(
    action_type: str,
    action_description: str,
    tool_name: str = None,
    tool_args: Dict[str, Any] = None,
    context: str = ""
) -> ActionReview:
    """Review a proposed action before execution.

    Args:
        action_type: Type of action (e.g., 'edit', 'delete', 'run_cmd')
        action_description: Description of what the action does
        tool_name: Name of the tool being called
        tool_args: Arguments for the tool call
        context: Additional context about current task

    Returns:
        ActionReview with approval decision and feedback
    """
    review = ActionReview()

    # Quick security checks (pre-LLM)
    security_issues = _quick_security_check(tool_name, tool_args, action_description)
    if security_issues:
        review.security_warnings.extend(security_issues)
        # Don't auto-reject, but flag for review

    # Prepare action summary
    action_summary = {
        "action_type": action_type,
        "description": action_description,
        "tool": tool_name,
        "arguments": tool_args,
        "context": context
    }

    # Get LLM review
    messages = [
        {"role": "system", "content": ACTION_REVIEW_SYSTEM},
        {"role": "user", "content": f"""Review this proposed action:

{json.dumps(action_summary, indent=2)}

Should this action be approved?"""}
    ]

    response = ollama_chat(messages)

    if "error" in response:
        # Default to approved if review unavailable
        review.approved = True
        review.concerns.append("Review agent unavailable")
        return review

    # Parse review
    try:
        content = response.get("message", {}).get("content", "")
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            review_data = json.loads(json_match.group(0))
            review.approved = review_data.get("approved", True)
            review.recommendation = review_data.get("recommendation", "")
            review.concerns = review_data.get("concerns", [])
            review.security_warnings.extend(review_data.get("security_warnings", []))
            review.alternative_approaches = review_data.get("alternative_approaches", [])
    except Exception as e:
        # Default to approved on parse error
        review.approved = True
        review.concerns.append(f"Parse error: {e}")

    return review


def _quick_security_check(tool_name: str, tool_args: Dict[str, Any], description: str) -> List[str]:
    """Perform quick security checks without LLM.

    Args:
        tool_name: Name of tool being called
        tool_args: Tool arguments
        description: Action description

    Returns:
        List of security warnings
    """
    warnings = []

    if not tool_args:
        tool_args = {}

    # Check for command injection patterns
    if tool_name == "run_cmd":
        cmd = tool_args.get("command", "")
        # Check for shell injection patterns
        dangerous_patterns = [";", "&&", "||", "|", "`", "$(", "${"]
        if any(pattern in cmd for pattern in dangerous_patterns):
            warnings.append("Command contains shell operators - verify no injection vulnerability")

    # Check for exposed secrets in code
    if tool_name in ["write_file", "edit_file"]:
        content = str(tool_args.get("content", "")) + str(tool_args.get("new_content", ""))
        secret_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api[_-]?key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
        ]
        for pattern in secret_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append("Possible hardcoded secret detected - use environment variables")
                break

    # Check for SQL injection in database operations
    if "sql" in description.lower() or "query" in description.lower():
        if "'" in str(tool_args) or '"' in str(tool_args):
            warnings.append("Possible SQL injection - verify parameterized queries are used")

    # Check for path traversal
    if tool_name in ["read_file", "write_file", "delete_file"]:
        path = tool_args.get("file_path", "")
        if ".." in path or path.startswith("/etc/") or path.startswith("/root/"):
            warnings.append("Suspicious file path detected - verify this is intentional")

    return warnings


def _display_plan_review(review: PlanReview, plan: ExecutionPlan):
    """Display plan review results.

    Args:
        review: The review to display
        plan: The original plan being reviewed
    """
    print("\n" + "=" * 60)
    print("REVIEW RESULTS")
    print("=" * 60)

    # Decision
    decision_emoji = {
        ReviewDecision.APPROVED: "✅",
        ReviewDecision.APPROVED_WITH_SUGGESTIONS: "✅",
        ReviewDecision.REQUIRES_CHANGES: "⚠️",
        ReviewDecision.REJECTED: "❌"
    }
    emoji = decision_emoji.get(review.decision, "❓")
    print(f"\nDecision: {emoji} {review.decision.value.upper().replace('_', ' ')}")
    print(f"Confidence: {review.confidence_score:.0%}")

    if review.overall_assessment:
        print(f"\n{review.overall_assessment}")

    # Issues
    if review.issues:
        print(f"\n🔍 Issues Found ({len(review.issues)}):")
        for issue in review.issues:
            severity = issue.get("severity", "unknown").upper()
            task_id = issue.get("task_id")
            desc = issue.get("description", "")
            impact = issue.get("impact", "")

            severity_emoji = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢"
            }.get(severity, "⚪")

            print(f"  {severity_emoji} [{severity}] Task #{task_id + 1}: {desc}")
            if impact:
                print(f"     Impact: {impact}")

    # Security concerns
    if review.security_concerns:
        print(f"\n🔒 Security Concerns ({len(review.security_concerns)}):")
        for concern in review.security_concerns:
            print(f"  - {concern}")

    # Missing tasks
    if review.missing_tasks:
        print(f"\n➕ Missing Tasks ({len(review.missing_tasks)}):")
        for task in review.missing_tasks:
            print(f"  - {task}")

    # Unnecessary tasks
    if review.unnecessary_tasks:
        print(f"\n➖ Unnecessary Tasks:")
        for task_id in review.unnecessary_tasks:
            if task_id < len(plan.tasks):
                print(f"  - Task #{task_id + 1}: {plan.tasks[task_id].description}")

    # Suggestions
    if review.suggestions:
        print(f"\n💡 Suggestions ({len(review.suggestions)}):")
        for suggestion in review.suggestions:
            print(f"  - {suggestion}")

    print("=" * 60)


def display_action_review(review: ActionReview, action_description: str):
    """Display action review results.

    Args:
        review: The action review
        action_description: Description of the action
    """
    if not review.approved:
        print(f"\n❌ Action blocked: {action_description}")
    elif review.concerns or review.security_warnings:
        print(f"\n⚠️  Action approved with concerns: {action_description}")

    if review.security_warnings:
        print("🔒 Security Warnings:")
        for warning in review.security_warnings:
            print(f"  - {warning}")

    if review.concerns:
        print("⚠️  Concerns:")
        for concern in review.concerns:
            print(f"  - {concern}")

    if review.alternative_approaches:
        print("💡 Alternative Approaches:")
        for alt in review.alternative_approaches:
            print(f"  - {alt}")

    if review.recommendation:
        print(f"📋 Recommendation: {review.recommendation}")
