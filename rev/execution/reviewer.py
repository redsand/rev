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
from rev.tools.registry import get_available_tools


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
        self.confidence_score: float = 0.7  # 0.0 to 1.0, default 0.7

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


def _extract_bullets(text: str) -> List[str]:
    """Extract bullet-style lines from freeform text."""
    bullets = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("-", "*")):
            bullets.append(stripped.lstrip("-* ").strip())
    return [b for b in bullets if b]


def _clean_review_string(value: Any) -> str:
    """Normalize reviewer-provided strings for display and downstream logic."""

    if value is None:
        return ""

    cleaned = str(value)
    cleaned = cleaned.translate({
        ord("\u200B"): None,  # zero width space
        ord("\u200C"): None,  # zero width non-joiner
        ord("\u200D"): None,  # zero width joiner
        ord("\uFEFF"): None,  # BOM / zero width no-break space
    })
    return cleaned.strip()


def _apply_freeform_review(review: "PlanReview", content: str) -> bool:
    """Fallback parsing when the review agent returns plain text instead of JSON."""
    if not content or not content.strip():
        return False

    review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
    review.overall_assessment = content.strip()
    review.confidence_score = 0.65

    suggestions = _extract_bullets(content)
    if not suggestions:
        suggestions = [content.strip()[:200]]
    review.suggestions = [_clean_review_string(s) for s in suggestions if _clean_review_string(s)]
    return True


def _extract_json_substrings(content: str) -> List[str]:
    """Extract balanced JSON object substrings from text, ignoring braces inside strings."""
    substrings = []
    depth = 0
    start_idx = None
    in_string = False
    escape = False

    for index, char in enumerate(content):
        if char == '"' and not escape:
            in_string = not in_string
            escape = False
            if in_string:
                continue
            else:
                continue

        if in_string:
            if char == '\\' and not escape:
                escape = True
            else:
                escape = False
            continue

        if char == '{':
            if depth == 0:
                start_idx = index
            depth += 1
        elif char == '}' and depth > 0:
            depth -= 1
            if depth == 0 and start_idx is not None:
                substrings.append(content[start_idx:index + 1])
                start_idx = None

    return substrings


def _parse_json_from_text(content: str) -> Optional[Dict[str, Any]]:
    """Try to parse JSON from the provided text."""
    if not content or not content.strip():
        return None

    stripped = content.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for candidate in _extract_json_substrings(content):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    return None


def _detect_vague_tasks_in_plan(plan: "ExecutionPlan") -> List[Dict[str, Any]]:
    """Detect tasks with vague placeholders in an execution plan.

    This is a pre-LLM check to quickly identify plans that need discovery phases.

    Args:
        plan: The execution plan to check

    Returns:
        List of vague task info dicts with task_id, description, and reason
    """
    vague_tasks = []

    # Vague placeholder patterns
    vague_patterns = [
        ("first identified", "Uses ordinal placeholder 'first identified' - specify the actual name"),
        ("second identified", "Uses ordinal placeholder - specify the actual name"),
        ("third identified", "Uses ordinal placeholder - specify the actual name"),
        ("the identified", "Uses generic 'the identified' - specify what was identified"),
        ("identified feature", "Uses vague 'identified feature' - name the specific feature"),
        ("identified analyst", "Uses vague 'identified analyst' - name the specific analyst class"),
        ("identified class", "Uses vague 'identified class' - name the specific class"),
        ("relevant code", "Uses vague 'relevant code' - specify which code"),
        ("relevant functionality", "Uses vague 'relevant functionality' - specify what functionality"),
        ("missing feature", "Uses vague 'missing feature' - name the specific feature"),
        ("missing module", "Uses vague 'missing module' - name the specific module"),
        ("from the other", "Uses vague 'from the other' - specify the source path and item"),
        ("from external", "Uses vague 'from external' - specify the source path and item"),
        ("first new", "Uses ordinal placeholder - specify the actual item name"),
        ("second new", "Uses ordinal placeholder - specify the actual item name"),
        ("port each", "Uses batch placeholder - create individual tasks per item"),
        ("implement each", "Uses batch placeholder - create individual tasks per item"),
    ]

    for task in plan.tasks:
        desc_lower = task.description.lower()
        for pattern, reason in vague_patterns:
            if pattern in desc_lower:
                vague_tasks.append({
                    "task_id": task.task_id,
                    "description": task.description,
                    "reason": reason
                })
                break  # Only report first match per task

    return vague_tasks


def _check_requirements_coverage(plan: "ExecutionPlan", user_request: str) -> List[str]:
    """Check if user request requirements are covered in the plan.

    Args:
        plan: The execution plan to check
        user_request: The original user request

    Returns:
        List of uncovered requirements
    """
    uncovered = []
    request_lower = user_request.lower()

    # Check for common requirements
    requirement_checks = [
        ("matrix recipe", "add to matrix recipe", "No task addresses adding to matrix recipes"),
        ("registry", "register", "No task addresses registration requirement"),
        ("config", "configuration", "No task addresses configuration update"),
        ("do not duplicate", "duplicate", "No task addresses duplicate avoidance check"),
        ("avoid duplicate", "duplicate", "No task addresses duplicate avoidance check"),
        ("test", "test", "No task addresses testing requirement"),
    ]

    for keyword, plan_keyword, message in requirement_checks:
        if keyword in request_lower:
            # Check if any task mentions this
            covered = any(
                plan_keyword in t.description.lower()
                for t in plan.tasks
            )
            if not covered and message not in uncovered:
                uncovered.append(message)

    return uncovered


PLAN_REVIEW_SYSTEM = """You are an expert plan review agent.

You have access to code analysis tools to verify plans:
- analyze_ast_patterns: AST-based pattern matching for Python code
- run_pylint: Comprehensive static code analysis
- run_mypy: Static type checking
- run_radon_complexity: Code complexity metrics
- find_dead_code: Dead code detection
- run_all_analysis: Combined analysis suite
- search_code: Search code using regex
- list_dir: List files matching patterns
- read_file: Read file contents

Use these tools to verify the plan is realistic and complete!

Your job is to review execution plans and identify:
1) Completeness: Are all necessary tasks included?
2) Correctness: Do the tasks achieve the stated goal?
3) Dependencies: Are dependencies correct and complete?
4) Risk: Are risks assessed and mitigated?
5) Security: Does the plan introduce likely vulnerabilities?
6) Best practices: Does the plan follow common patterns for this repo?
7) Edge cases: Are relevant edge cases covered?
8) Performance: Any likely performance pitfalls?
9) Maintainability: Will the changes be maintainable?
10) Testing: Are tests included and runnable?
11) Reuse: Does the plan duplicate existing functionality? Prefer extending existing code over new files.
12) SPECIFICITY: Do tasks contain SPECIFIC names (classes, functions, files) or VAGUE placeholders?

CRITICAL - VAGUE PLACEHOLDER DETECTION:
If a plan contains vague terms like "the identified feature", "the first analyst", "relevant code",
or "missing functionality", this implies the agent does NOT actually know what it is building.

VAGUE TASKS TO REJECT:
- "Implement the first identified analyst" -> REJECT: Which analyst? Name it.
- "Port the feature from the other repo" -> REJECT: Which feature? Name the class/function.
- "Add relevant functionality" -> REJECT: What functionality specifically?
- "Implement missing features" -> REJECT: Which features? List them by name.

GOOD SPECIFIC TASKS TO APPROVE:
- "Port 'MovingAverageCrossover' class from ../external/analysts.py"
- "Implement 'calculate_rsi' function in indicators.py"
- "Add 'BollingerBandAnalyst' to the matrix_recipes.py registry"

WHEN YOU DETECT VAGUE TASKS:
1. Set decision to "requires_changes"
2. In your suggestions, INSTRUCT the planner to switch to a RESEARCH/DISCOVERY phase first
3. Specify: "Before implementation, create tasks to IDENTIFY and LIST the specific items to port/implement"
4. Example suggestion: "Add a discovery task: 'Scan ../external-repo to list all Analyst classes available for porting'"

REQUIREMENTS COVERAGE:
Check if the user request contains explicit constraints (e.g., "do not duplicate", "add to matrix recipes").
If these constraints are NOT addressed by any task in the plan, flag them as missing_tasks.

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

STRICT JSON OUTPUT REQUIREMENTS:
- You must return ONLY the JSON object matching the schema above.
- Do NOT wrap the JSON in code fences or markdown.
- Do NOT include any explanatory text before or after the JSON.
- If uncertain about a value, use an empty list or null-equivalent in JSON.

Be thorough but practical. Focus on issues that could cause real problems.
PRIORITIZE specificity - vague plans cannot be executed correctly."""


ACTION_REVIEW_SYSTEM = """You are an expert security and best practices review agent.

You have access to code analysis tools to help verify actions:
- analyze_ast_patterns, run_pylint, run_mypy, run_radon_complexity, find_dead_code
- search_code, list_dir, read_file

Your job is to review individual actions (tool calls, code changes) before execution.

Critical distinction:
- Review code for security flaws introduced by the change.
- Treat local build/test tooling as trusted; do not block standard developer commands.
- Only flag command execution when there is evidence of injection from user-controlled input.

Analyze each action for:
1) Security in code: SQL injection, XSS, command injection, secrets
2) Safety: data loss, destructive operations, breaking changes
3) Correctness: logic errors, incorrect assumptions
4) Best practices: maintainability, performance
5) Alternatives: better approaches if applicable

DO NOT flag as security issues:
- Hardcoded paths in build commands (these are local development tools)
- Compiler invocations with known paths (cl.exe, gcc, etc.)
- Build system commands (cmake, make, msbuild, etc.)
- Test runner commands with fixed parameters
- Package manager commands (npm, pip, cargo, etc.)

DO flag as security issues:
- Code that concatenates user input into SQL queries
- Code that uses eval() or exec() with external input
- Code that writes secrets/passwords/tokens into source files
- Code that builds shell commands from unsanitized user input
- Code that lacks input validation at system boundaries

Return your review in JSON format:
{
  "approved": true,
  "recommendation": "Brief recommendation",
  "concerns": [
    "Specific concern about this action"
  ],
  "security_warnings": [
    "Security issue found in CODE"
  ],
  "alternative_approaches": [
    "Consider using X instead because..."
  ]
}

Be practical - don't block reasonable actions over minor style issues.
Focus on preventing real bugs and security issues IN THE CODE BEING WRITTEN."""


def review_execution_plan(
    plan: ExecutionPlan,
    user_request: str,
    strictness: ReviewStrictness = ReviewStrictness.MODERATE,
    auto_approve_low_risk: bool = True,
    max_parse_retries: int = 1,
    **kwargs,
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

    # Get available tools for LLM function calling
    tools = get_available_tools()

    review = PlanReview()

    # PRE-LLM CHECK: Detect vague placeholder tasks
    print("→ Checking for vague placeholder tasks...")
    vague_tasks = _detect_vague_tasks_in_plan(plan)
    if vague_tasks:
        print(f"  ⚠️  Found {len(vague_tasks)} task(s) with vague placeholders:")
        for vt in vague_tasks:
            print(f"     Task #{vt['task_id'] + 1}: {vt['reason']}")
            review.issues.append({
                "severity": "high",
                "task_id": vt["task_id"],
                "description": f"Vague task: {vt['reason']}",
                "impact": "Cannot execute tasks without knowing specific targets"
            })

        # Auto-reject if vague tasks found (high severity)
        review.decision = ReviewDecision.REQUIRES_CHANGES
        review.overall_assessment = (
            f"Plan contains {len(vague_tasks)} vague task(s) with placeholder references. "
            "The planner must first run a DISCOVERY phase to identify specific class/function names."
        )
        review.suggestions.append(
            "Switch to RESEARCH/DISCOVERY phase: Add tasks to scan and list specific items before implementing"
        )
        review.suggestions.append(
            "Replace vague tasks like 'implement the identified X' with specific tasks like 'implement ClassNameHere'"
        )
        review.confidence_score = 0.90
        _display_plan_review(review, plan)
        return review

    # PRE-LLM CHECK: Verify requirements coverage
    print("→ Checking requirements coverage...")
    uncovered_requirements = _check_requirements_coverage(plan, user_request)
    if uncovered_requirements:
        print(f"  ⚠️  Found {len(uncovered_requirements)} uncovered requirement(s):")
        for ureq in uncovered_requirements:
            print(f"     - {ureq}")
            review.missing_tasks.append(ureq)

    # Quick check: If all tasks are low risk, auto-approve if enabled
    if auto_approve_low_risk and not uncovered_requirements:
        all_low_risk = all(task.risk_level == RiskLevel.LOW for task in plan.tasks)
        if all_low_risk and len(plan.tasks) > 0:
            print("→ All tasks are low-risk and requirements covered. Auto-approving.")
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
    plan_prompt = f"""Review this execution plan:

{json.dumps(plan_summary, indent=2)}

Strictness level: {strictness.value}

Return ONLY valid JSON per the schema. Do not include any other text or formatting.

Provide a thorough review."""
    messages = [
        {"role": "system", "content": PLAN_REVIEW_SYSTEM},
        {"role": "user", "content": plan_prompt}
    ]

    print("→ Analyzing plan with review agent...")
    parse_attempt = 0
    while parse_attempt <= max_parse_retries:
        response = ollama_chat(messages, tools=tools) or {}

        if not isinstance(response, dict):
            print("⚠️  Review agent returned no response; approving with suggestions by default")
            review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
            review.suggestions.append("Review agent unavailable - plan approved by default")
            review.confidence_score = 0.7
            return review

        if "error" in response:
            print(f"⚠️  Review agent error: {response['error']}")
            # Default to approved with warning
            review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
            review.suggestions.append("Review agent unavailable - plan approved by default")
            review.confidence_score = 0.7
            return review

        try:
            content = response.get("message", {}).get("content", "")
            review_data = _parse_json_from_text(content)
            if not review_data:
                raise ValueError("No JSON object found in review response")

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
            # Handle non-numeric confidence scores gracefully
            try:
                review.confidence_score = float(review_data.get("confidence_score", 0.8))
            except (ValueError, TypeError):
                review.confidence_score = 0.7  # Default fallback for malformed LLM response
            review.issues = review_data.get("issues", []) or []
            review.suggestions = [
                _clean_review_string(s)
                for s in (review_data.get("suggestions", []) or [])
                if _clean_review_string(s)
            ]
            review.security_concerns = [
                _clean_review_string(s)
                for s in (review_data.get("security_concerns", []) or [])
                if _clean_review_string(s)
            ]
            review.missing_tasks = [
                _clean_review_string(s)
                for s in (review_data.get("missing_tasks", []) or [])
                if _clean_review_string(s)
            ]
            review.unnecessary_tasks = review_data.get("unnecessary_tasks", []) or []
            break  # Parsed successfully

        except Exception as e:
            parse_attempt += 1
            print(f"⚠️  Error parsing review: {e}")
            print("??  Review request prompt:")
            print(plan_prompt)
            print("??  Raw review response content:")
            print(content)
            if parse_attempt > max_parse_retries:
                if _apply_freeform_review(review, content):
                    print("⚠️  Falling back to freeform review parsing.")
                    break
                review.decision = ReviewDecision.APPROVED_WITH_SUGGESTIONS
                review.suggestions.append("Could not parse review - approved by default")
                review.confidence_score = 0.7
                break
            retry_instruction = (
                "Your previous response could not be parsed as JSON. "
                f"Error: {e}.\n"
                "The raw response was:\n" 
                "============================================================\n"
                f"{content}\n"
                "============================================================\n"
                "Return ONLY valid JSON that matches the required schema with no additional text."
            )

            messages.append({"role": "assistant", "content": str(content)})
            messages.append({"role": "user", "content": retry_instruction})
            print("⚠️  Retrying review agent once due to parse failure with strict JSON reminder...")
            continue

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
    # Get available tools for LLM function calling
    tools = get_available_tools()

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

    response = ollama_chat(messages, tools=tools)

    if "error" in response:
        # Default to approved if review unavailable
        review.approved = True
        review.concerns.append("Review agent unavailable")
        return review

    # Parse review
    try:
        content = response.get("message", {}).get("content", "")
        review_data = _parse_json_from_text(content)
        if review_data:
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

    # Trusted development tools - don't flag as security issues
    TRUSTED_BUILD_TOOLS = [
        'cl.exe', 'gcc', 'g++', 'clang', 'clang++',  # Compilers
        'link.exe', 'ld', 'lld',  # Linkers
        'cmake', 'make', 'nmake', 'msbuild', 'ninja',  # Build systems
        'cargo', 'npm', 'pip', 'yarn', 'go build',  # Package managers
        'pytest', 'jest', 'mocha', 'cargo test',  # Test runners
        'python -m', 'node ', 'javac', 'java ',  # Language runtimes
    ]

    # Check for command execution patterns
    if tool_name == "run_cmd":
        cmd = tool_args.get("cmd") or tool_args.get("command", "")
        cmd_lower = cmd.lower()

        # Skip security checks for trusted build/dev tools
        is_trusted_tool = any(tool in cmd_lower for tool in TRUSTED_BUILD_TOOLS)
        if is_trusted_tool:
            # Trusted tools can have hardcoded paths, shell operators, etc.
            # These are local development commands, not user-facing code
            return warnings

        # For other commands, check for dangerous patterns
        # Only flag if there's evidence of actual injection risk
        dangerous_patterns = {
            ';': 'Command chaining',
            '&&': 'Command chaining',
            '||': 'Command chaining',
            '|': 'Pipe operator',
            '$(': 'Command substitution',
            '`': 'Command substitution',
            '${': 'Variable expansion',
        }
        for pattern, desc in dangerous_patterns.items():
            if pattern in cmd:
                warnings.append(f"{desc} detected in command - verify no injection from user input")
                break

    # Check for exposed secrets in CODE being written
    if tool_name in ["write_file", "apply_patch"]:
        content = str(tool_args.get("content", "")) + str(tool_args.get("patch", ""))
        secret_patterns = [
            (r'password\s*=\s*["\'][^"\']+["\']', 'hardcoded password'),
            (r'api[_-]?key\s*=\s*["\'][^"\']+["\']', 'hardcoded API key'),
            (r'secret\s*=\s*["\'][^"\']+["\']', 'hardcoded secret'),
            (r'token\s*=\s*["\'][^"\']+["\']', 'hardcoded token'),
            (r'-----BEGIN (PRIVATE|RSA) KEY-----', 'private key'),
        ]
        for pattern, name in secret_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append(f"Possible {name} in code - use environment variables or secret management")
                break

    # Check for SQL injection vulnerabilities IN CODE
    if tool_name in ["write_file", "apply_patch"]:
        content = str(tool_args.get("content", "")) + str(tool_args.get("patch", ""))
        # Look for string concatenation in SQL queries (sign of SQL injection)
        sql_injection_patterns = [
            r'execute\([^)]*\+[^)]*\)',  # execute("SELECT * FROM" + user_input)
            r'query\([^)]*\+[^)]*\)',    # query("SELECT * FROM" + user_input)
            r'f["\']SELECT.*\{.*\}',     # f"SELECT * FROM {table}"
            r'["\']SELECT.*["\'].*\+',   # "SELECT * FROM users WHERE id = " + user_id
            r'["\']INSERT.*["\'].*\+',   # "INSERT INTO users VALUES (" + values
            r'["\']UPDATE.*["\'].*\+',   # "UPDATE users SET name = " + name
            r'["\']DELETE.*["\'].*\+',   # "DELETE FROM users WHERE id = " + id
        ]
        for pattern in sql_injection_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append("Possible SQL injection - use parameterized queries instead of string concatenation")
                break

    # Check for command injection vulnerabilities IN CODE
    if tool_name in ["write_file", "apply_patch"]:
        content = str(tool_args.get("content", "")) + str(tool_args.get("patch", ""))
        # Look for shell command construction from user input
        cmd_injection_patterns = [
            r'os\.system\([^)]*\+',  # os.system("cmd " + user_input)
            r'subprocess\.\w+\([^)]*\+',  # subprocess.call("cmd " + input)
            r'exec\([^)]*\+',  # exec("code " + user_input)
            r'eval\(',  # eval() is almost always dangerous
        ]
        for pattern in cmd_injection_patterns:
            if re.search(pattern, content):
                warnings.append("Possible command injection - avoid string concatenation in shell commands and eval/exec")
                break

    # Check for path traversal vulnerabilities IN CODE
    if tool_name in ["write_file", "apply_patch"]:
        content = str(tool_args.get("content", "")) + str(tool_args.get("patch", ""))
        if re.search(r'open\([^)]*\+', content) or re.search(r'file_path\s*=.*\+', content):
            warnings.append("Possible path traversal - validate and sanitize file paths from user input")

    # Check for path traversal in file operations
    if tool_name in ["read_file", "write_file", "delete_file"]:
        path = tool_args.get("file_path", "")
        if ".." in path or path.startswith("/etc/") or path.startswith("/root/"):
            warnings.append("Suspicious file path detected - verify this is intentional")

    # Check for SQL injection in database operation descriptions
    # (this is a heuristic check for when SQL is being executed)
    if "sql" in description.lower() or "query" in description.lower():
        if "'" in str(tool_args) or '"' in str(tool_args):
            warnings.append("Possible SQL injection - verify parameterized queries are used")

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

            # Check if task_id is a valid integer before trying to add to it
            if isinstance(task_id, (int, float)) and task_id is not None:
                print(f"  {severity_emoji} [{severity}] Task #{int(task_id) + 1}: {desc}")
            else:
                print(f"  {severity_emoji} [{severity}] {desc}")
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


def format_review_feedback_for_llm(review: ActionReview, action_description: str, tool_name: str = None) -> str:
    """Format action review feedback for LLM consumption.

    This creates a structured message that the LLM can understand and act upon,
    allowing it to adjust its approach based on reviewer feedback.

    Args:
        review: The action review results
        action_description: Description of the action that was reviewed
        tool_name: Name of the tool that was called (optional)

    Returns:
        Formatted feedback string for inclusion in LLM conversation
    """
    if not review.concerns and not review.security_warnings and not review.alternative_approaches:
        # No feedback to provide
        return None

    feedback_parts = [
        "=== REVIEW FEEDBACK ===",
        f"Action: {action_description}"
    ]

    if tool_name:
        feedback_parts.append(f"Tool: {tool_name}")

    if review.approved:
        feedback_parts.append("Status: Approved with concerns")
    else:
        feedback_parts.append("Status: BLOCKED - Action was not approved")

    if review.security_warnings:
        feedback_parts.append("\n🔒 SECURITY WARNINGS:")
        for warning in review.security_warnings:
            feedback_parts.append(f"  - {warning}")

    if review.concerns:
        feedback_parts.append("\n⚠️  CONCERNS:")
        for concern in review.concerns:
            feedback_parts.append(f"  - {concern}")

    if review.alternative_approaches:
        feedback_parts.append("\n💡 ALTERNATIVE APPROACHES:")
        for i, alt in enumerate(review.alternative_approaches, 1):
            feedback_parts.append(f"  {i}. {alt}")

    if review.recommendation:
        feedback_parts.append(f"\n📋 RECOMMENDATION: {review.recommendation}")

    if not review.approved:
        feedback_parts.append("\nPlease choose a different approach to accomplish this task.")
    else:
        feedback_parts.append("\nPlease consider this feedback in your next actions and adjust your approach if needed.")

    feedback_parts.append("===================")

    return "\n".join(feedback_parts)
