"""
Execution planning mode for generating comprehensive task plans.

This module provides the planning phase functionality that analyzes a user request
and generates a detailed execution plan with task dependency analysis, risk
assessment, and validation steps.
"""

import re
import json
import sys
from typing import Dict, Any, List, Optional

from rev.models.task import ExecutionPlan, RiskLevel, Task, TaskStatus
from rev.llm.client import ollama_chat
from rev.config import (
    MAX_LLM_TOKENS_PER_RUN,
    MAX_PLAN_TASKS,
    MAX_PLANNING_TOOL_ITERATIONS,
    ensure_escape_is_cleared,
    get_system_info_cached,
)
from rev import config
from rev.tools.git_ops import get_repo_context
from rev.tools.registry import get_available_tools, execute_tool


PLANNING_SYSTEM = """You are a planning agent. Produce an execution plan for the user request.

Priorities:
1) Reuse first: prefer extending existing code and patterns; avoid duplication.
2) Make tasks executable: small, concrete, ordered, and test-aware.
3) Limit exploration: gather only essential context, then generate the plan.

CRITICAL REQUIREMENT:
- You MUST generate AT LEAST 2 distinct tasks
- NEVER collapse everything into a single task
- Break down work into review/analysis + implementation + testing phases
- If you're unsure, create separate tasks for: review, implementation, and validation

CRITICAL RULE: DO NOT Hallucinate File Paths or Class Names
- You can ONLY reference file paths, class names, and function names that appear EXPLICITLY in:
  * The repository context provided to you
  * Research findings from your tool calls
  * The current conversation
- If you suspect a file/class exists but do NOT see it in the provided context, you CANNOT create an [ADD] or [EDIT] task for it.
- Instead, you MUST create a [REVIEW] or discovery task first: "Scan [directory] for '[pattern]' to identify specific items."

CRITICAL CONSTRAINT - CONCRETE NOUNS ONLY:
You generally cannot create tasks with placeholders or vague references.

BAD (too vague - will be REJECTED):
- "Implement the first identified analyst."
- "Port the feature from the other repo."
- "Add the identified functionality."
- "Implement relevant code from external source."

GOOD (specific and actionable):
- "Port 'RSI_Strategy' class from '../other-repo/strategies.py' to 'lib/analysts.py'."
- "Implement 'MovingAverageCrossover' analyst based on existing 'BollingerBand' pattern."
- "Add 'calculate_macd' function to indicators.py following existing indicator pattern."

IF YOU DO NOT KNOW THE SPECIFIC NAMES of the classes, functions, or features to implement:
1. Do NOT generate an implementation plan with placeholders.
2. Generate a RESEARCH/DISCOVERY plan first to identify the specific items.
3. Your first task MUST be: "Scan [source] to identify and list specific [items] to [action]."
4. Only after discovery tasks can you add implementation tasks.

TWO-STAGE PLANNING - DISCOVERY CAPABILITY:
- Stage A (Discovery): If specific items are unknown, create tasks to IDENTIFY them first.
- Stage B (Execution): Only create implementation tasks AFTER you have specific names/targets.

IF THE RESEARCH IS INSUFFICIENT:
If the user wants to port features but the specific source files are not listed in the context:
1. Do NOT generate coding tasks with vague placeholders.
2. Generate a "Discovery Plan" consisting of [REVIEW] tasks to list/search the external files.
3. Example Discovery Plan:
   - [REVIEW] "List all files in ../algorithmic-trading-with-python/listings/ to identify available modules"
   - [REVIEW] "Grep for 'class .*Strategy' in ../algorithmic-trading-with-python to find strategy implementations"
   - [REVIEW] "Scan ../external-repo for 'MovingAverage' implementations to identify specific classes to port"

Tool usage:
- You may call 1-3 tools to gather essential context (list_dir, search_code, read_file).
- After gathering context, IMMEDIATELY generate the plan as a JSON array.
- Do NOT exhaustively explore - if you need more info, create review tasks in the plan.
- If tool calling is unavailable, produce a best-effort plan with initial review tasks.

CRITICAL - Output Format (PURE JSON ONLY):
You MUST output PURE JSON and NOTHING ELSE.
- Do NOT wrap the output in markdown code blocks (```json or ```).
- Do NOT include ANY conversational text before or after the JSON.
- Do NOT add explanations like "Here's the plan:" or "This plan will...".
- Do NOT include comments or reasoning outside the JSON structure.
- If you need to include thoughts or reasoning, put them in a JSON field like "_reasoning": "...".
- Your ENTIRE response must be ONLY the JSON array, starting with [ and ending with ].

Output format (strict):
- Return ONLY a JSON array. No prose, no markdown, no code fences.
- Each item must be an object with exactly:
  - "description": string
  - "action_type": "review" | "edit" | "add" | "delete" | "test" | "doc"
  - "complexity": "low" | "medium" | "high"

Guidance:
- Put review tasks first (find existing implementations and patterns).
- For multi-feature work: one implementation task per feature with SPECIFIC names.
- For code changes: include at least one test task and name the command when possible.
- If a task creates a new file, the description must say why reuse was not possible.
- When in doubt, create review tasks instead of calling more tools.
- ALWAYS include specific file paths, class names, or function names in task descriptions.

MINIMUM TASK BREAKDOWN:
- At minimum: [review/analysis task] + [implementation task]
- Better: [review] + [implementation] + [test]
- Best: [review] + [multiple specific implementation tasks] + [test] + [validation]

REQUIREMENTS CHECKLIST:
When the user request contains specific constraints (e.g., "do not duplicate", "add to registry",
"include in config"), ensure EVERY constraint has a corresponding task in your plan."""


CODING_PLANNING_SUFFIX = """
You are planning a CODE + TEST change to this repository.

In addition to the general planning rules above, you MUST:

1. Identify the specific files and modules you will touch.
2. For every non-trivial code change ("edit" or "add"):
   - Add at least one task to CREATE or UPDATE automated tests.
   - Add at least one task to RUN the relevant test command.
3. Prefer many small, atomic tasks over a few large ones.

Use these action_type values:
- "review": analyzing existing code or architecture
- "edit": modifying existing code
- "add": creating new code or tests
- "delete": deleting code or files
- "test": running tests (pytest, npm test, go test, etc.)
- "doc": updating docs, READMEs, or comments

When possible, include hints in the description about:
- which test file or directory is affected
- which test command should be used (e.g. "pytest tests/api", "npm test").

Your goal is to produce a PLAN that explicitly couples code changes with tests and docs.
"""


BREAKDOWN_SYSTEM = """You break down a broad task into small, independently executable subtasks.

CRITICAL REQUIREMENT:
- You MUST return AT LEAST 3 subtasks (minimum)
- NEVER return a single task that just rephrases the original request
- Break work into distinct phases: review/research, implementation(s), testing

CRITICAL RULE: DO NOT Hallucinate File Paths or Class Names
- You can ONLY reference file paths, class names, and function names that appear EXPLICITLY in the context provided to you.
- If you suspect a file/class exists but do NOT see it in the context, you CANNOT create an [ADD] or [EDIT] task for it.
- Instead, you MUST create a [REVIEW] or discovery task first.

CRITICAL CONSTRAINT - CONCRETE NOUNS ONLY:
You MUST use specific names in task descriptions. NEVER use placeholders.

BAD (WILL BE REJECTED):
- "Implement first missing feature/module"
- "Port the identified analyst"
- "Add relevant functionality"

GOOD (SPECIFIC AND ACTIONABLE):
- "Implement 'BollingerBandAnalyst' class in lib/analysts.py"
- "Port 'MacdStrategy' from ../external/strategies.py to lib/strategies.py"
- "Add 'calculate_rsi' function to indicators.py"

IF SPECIFIC NAMES ARE UNKNOWN:
- Your first tasks MUST be discovery/research tasks to identify the specific items.
- Only AFTER discovery tasks can you add implementation tasks.
- Discovery task example: "Scan ../external-repo to list all Analyst classes to be ported"

IF THE RESEARCH IS INSUFFICIENT:
Generate a "Discovery Plan" with [REVIEW] tasks to identify specific items:
- "List all files in [directory] to identify available modules"
- "Grep for '[pattern]' in [directory] to find specific implementations"
- "Scan [source] for '[keyword]' to identify classes/functions to port"

Rules:
- Each subtask does one concrete thing.
- If the task implies multiple features/items, create one subtask per item WITH SPECIFIC NAMES.
- For porting/integration work: first IDENTIFY specific items, then implement one at a time, then add tests.
- Avoid a single subtask that covers the entire original task.

MINIMUM BREAKDOWN PATTERN:
1. Review/research task (understand existing code/patterns, IDENTIFY specific items)
2. One or more implementation tasks (each doing ONE specific thing WITH NAMED TARGET)
3. Testing/validation task

EXAMPLE for "implement features from another repository/framework" (WITH SPECIFIC NAMES):
[
  {"description": "Review existing codebase structure in lib/analysts.py to identify integration points", "action_type": "review", "complexity": "low"},
  {"description": "Scan ../algorithmic-trading-with-python to list all Analyst classes available", "action_type": "review", "complexity": "low"},
  {"description": "Compare external analysts with existing ones to identify non-duplicates", "action_type": "review", "complexity": "low"},
  {"description": "Port 'MovingAverageCrossoverAnalyst' from ../algorithmic-trading-with-python/analysts.py", "action_type": "add", "complexity": "medium"},
  {"description": "Port 'BollingerBandAnalyst' from ../algorithmic-trading-with-python/analysts.py", "action_type": "add", "complexity": "medium"},
  {"description": "Port 'MacdAnalyst' from ../algorithmic-trading-with-python/analysts.py", "action_type": "add", "complexity": "medium"},
  {"description": "Register new analysts in matrix_recipes.py configuration", "action_type": "edit", "complexity": "low"},
  {"description": "Write unit tests for MovingAverageCrossoverAnalyst, BollingerBandAnalyst, MacdAnalyst", "action_type": "add", "complexity": "medium"},
  {"description": "Run pytest tests/test_analysts.py to validate integration", "action_type": "test", "complexity": "low"}
]

CRITICAL - Output Format (PURE JSON ONLY):
You MUST output PURE JSON and NOTHING ELSE.
- Do NOT wrap the output in markdown code blocks (```json or ```).
- Do NOT include ANY conversational text before or after the JSON.
- Do NOT add explanations or reasoning outside the JSON.
- Your ENTIRE response must be ONLY the JSON array, starting with [ and ending with ].

Output format (strict): return ONLY a JSON array of objects with keys "description", "action_type", "complexity"."""


TOOL_RESULT_CHAR_LIMIT = 6000


def _truncate_tool_content(content: str, limit: int = TOOL_RESULT_CHAR_LIMIT) -> str:
    """Trim tool output to avoid overloading LLM context."""

    if content is None:
        return ""

    if len(content) <= limit:
        return content

    omitted = len(content) - limit
    preview = content[:limit]
    return (
        f"[tool output truncated to {limit} characters; {omitted} omitted]\n"
        f"{preview}"
    )


def _format_available_tools(tools: List[Dict[str, Any]]) -> str:
    """Format available tools for inclusion in planning prompt.

    Args:
        tools: List of tool definitions in OpenAI format

    Returns:
        Formatted string describing available tools
    """
    tool_descriptions = []

    for tool in tools:
        if tool.get("type") == "function":
            func = tool.get("function", {})
            name = func.get("name", "")
            description = func.get("description", "")

            # Categorize tools
            if any(keyword in name for keyword in ["memory", "valgrind", "asan", "sanitizer", "leak"]):
                category = "Memory Analysis"
            elif any(keyword in name for keyword in ["security", "vulnerability", "cve", "scan"]):
                category = "Security Analysis"
            elif any(keyword in name for keyword in ["pylint", "mypy", "radon", "analysis", "ast"]):
                category = "Static Analysis"
            elif any(keyword in name for keyword in ["mcp", "server"]):
                category = "MCP Servers"
            elif any(keyword in name for keyword in ["search", "grep", "find", "list", "tree"]):
                category = "Code Search"
            elif any(keyword in name for keyword in ["read", "write", "file"]):
                category = "File Operations"
            else:
                category = "General Tools"

            tool_descriptions.append(f"  - {name}: {description} [{category}]")

    if not tool_descriptions:
        return "  (No additional tools available)"

    # Group by category
    return "\n".join(sorted(set(tool_descriptions)))


def _execute_tool_calls(tool_calls: List[Dict], verbose: bool = True) -> List[Dict[str, Any]]:
    """Execute tool calls from LLM response and return results.

    Args:
        tool_calls: List of tool call dictionaries from LLM
        verbose: Whether to print tool execution info

    Returns:
        List of tool result messages for LLM
    """
    tool_results = []

    for tool_call in tool_calls:
        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name", "")
        arguments = function_info.get("arguments", {})

        # Parse arguments if they're a JSON string
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if verbose:
            print(f"  → Calling tool: {tool_name}")

        try:
            # Execute the tool
            result = execute_tool(tool_name, arguments)
            result = _truncate_tool_content(result)
            tool_results.append({
                "role": "tool",
                "content": result
            })
        except Exception as e:
            error_msg = f"Error executing {tool_name}: {str(e)}"
            if verbose:
                print(f"    ✗ {error_msg}")
            tool_results.append({
                "role": "tool",
                "content": json.dumps({"error": error_msg})
            })

    return tool_results


def _call_llm_with_tools(
    messages: List[Dict],
    tools: List[Dict],
    max_iterations: int = 5,
    model_name: Optional[str] = None,
    model_supports_tools: Optional[bool] = None,
) -> Dict[str, Any]:
    """Call LLM with tools, handling tool calling loop.

    Args:
        messages: Initial messages for LLM
        tools: Available tools
        max_iterations: Maximum tool calling iterations

    Returns:
        Final LLM response after tool calls complete
    """
    conversation = messages.copy()

    for iteration in range(max_iterations):
        # Add progressive pressure as iterations increase
        iteration_tools = tools if (model_supports_tools is not False) else None

        # Remove tools after 5 iterations to force plan generation
        if iteration >= 5:
            iteration_tools = None

        # After 3 iterations, start pressuring to generate plan
        if iteration >= 3 and iteration_tools:
            # Add reminder to conversation
            pressure_msg = {
                "role": "user",
                "content": f"You've used {iteration} tool calls. Generate the execution plan JSON array NOW. Stop exploring and create the plan."
            }
            if conversation[-1].get("role") != "user":
                conversation.append(pressure_msg)

        response = ollama_chat(
            conversation,
            tools=iteration_tools,
            model=model_name,
            supports_tools=model_supports_tools,
        ) or {}

        if not isinstance(response, dict):
            return {"error": "LLM returned no response during planning"}

        if "error" in response:
            return response

        message = response.get("message", {})

        # Check if LLM wants to call tools
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            # No more tool calls - return final response
            return response

        print(f"\n  Planning tool-iteration {iteration + 1}/{max_iterations}: LLM calling {len(tool_calls)} tool(s)...")

        # Add assistant message with tool calls to conversation
        conversation.append(message)

        # Execute tool calls and get results
        tool_results = _execute_tool_calls(tool_calls)

        # Add tool results to conversation
        conversation.extend(tool_results)

    # Max iterations reached - force plan generation
    print(f"  Warning: Max planning tool-iterations ({max_iterations}) reached")
    conversation.append({
        "role": "user",
        "content": """STOP calling tools. You have reached the iteration limit.

Generate the execution plan RIGHT NOW as a JSON array with this exact format:
[
  {"description": "task description", "action_type": "review", "complexity": "low"},
  {"description": "task description", "action_type": "edit", "complexity": "medium"}
]

Return ONLY the JSON array. No tools, no prose, just the JSON plan."""
    })

    final_response = ollama_chat(conversation, tools=None, model=model_name, supports_tools=model_supports_tools) or {}
    if not isinstance(final_response, dict):
        return {"error": "LLM returned no response during planning (final call)"}
    return final_response


def _is_overly_broad_task(task_description: str, user_request: str = "") -> bool:
    """Detect if a task description is too broad and needs breakdown.

    Returns True if the task is likely a high-level request that should be
    broken down into multiple granular subtasks.

    Args:
        task_description: The task description to check
        user_request: Optional original user request to compare against
    """
    description_lower = task_description.lower()

    # Check if task is just restating the user request (too similar)
    if user_request:
        # Remove common prefixes like "Review existing code and patterns for:"
        cleaned_task = task_description.lower()
        for prefix in ["review existing code and patterns for:", "review existing", "implement"]:
            if cleaned_task.startswith(prefix):
                cleaned_task = cleaned_task[len(prefix):].strip()

        # Compare word overlap
        task_words = set(cleaned_task.split())
        request_words = set(user_request.lower().split())
        if len(task_words) > 5 and len(request_words) > 5:
            overlap = len(task_words & request_words) / min(len(task_words), len(request_words))
            if overlap > 0.7:  # More than 70% word overlap
                return True

    # Indicators of broad/multi-step tasks
    broad_indicators = [
        # Multi-item references
        "many ", "multiple ", "several ", "various ", "all ",
        # Implementation scope
        "implement", "build", "create system", "add features",
        "framework", "integrate", "migration",
        # Analysis/review scope
        "analyze", "review all", "audit",
        # Generic goals
        "goal is to", "should be", "exponential",
        # File/module references suggesting multiple targets
        "analysts", "strategies", "indicators", "modules",
        # External reference suggesting integration work
        "from ../", "from another", "algorithmic", "trading"
    ]

    # Check for broad indicators
    has_broad_indicator = any(indicator in description_lower for indicator in broad_indicators)

    # Check task length - very long descriptions often indicate complex tasks
    is_long_description = len(task_description) > 200

    # Check for multiple distinct actions mentioned
    action_words = ["add", "implement", "create", "update", "modify", "review", "test", "integrate"]
    action_count = sum(1 for word in action_words if word in description_lower)
    has_multiple_actions = action_count >= 2

    return has_broad_indicator or is_long_description or has_multiple_actions


def _has_vague_placeholder(task_description: str) -> bool:
    """Detect if a task description contains vague placeholders instead of specific names.

    This implements the "Concrete Nouns" enforcement - tasks must have specific
    class names, function names, or file paths, not abstract references.

    Args:
        task_description: The task description to check

    Returns:
        True if the task contains vague placeholders that should be rejected
    """
    description_lower = task_description.lower()

    # Vague placeholder patterns that indicate the planner doesn't know what to do
    vague_patterns = [
        # Ordinal placeholders
        "first identified", "second identified", "third identified",
        "first missing", "second missing", "third missing",
        "first new", "second new", "third new",
        "first feature", "second feature", "third feature",
        # Generic references
        "the identified", "the relevant", "the appropriate",
        "identified feature", "identified analyst", "identified class",
        "identified function", "identified module", "identified item",
        "relevant feature", "relevant code", "relevant functionality",
        "appropriate feature", "appropriate implementation",
        # Placeholder phrases
        "from the other", "from external", "from source",
        "missing feature", "missing module", "missing functionality",
        "new feature/module", "feature/module",
        # Abstract implementation references
        "implement each", "implement all", "port each", "port all",
        "add each", "add all remaining",
        # Unknown targets
        "unknown target", "to be determined", "tbd",
    ]

    # Check for vague patterns
    for pattern in vague_patterns:
        if pattern in description_lower:
            return True

    # Check for ordinal + generic noun combinations
    ordinal_pattern = r'\b(first|second|third|fourth|fifth|next|remaining)\s+(identified|missing|new|relevant|appropriate)\b'
    if re.search(ordinal_pattern, description_lower):
        return True

    # Check for "the X" where X is a generic term without a specific name
    generic_the_pattern = r'\bthe\s+(feature|analyst|class|function|module|item|code|functionality)\b'
    matches = re.findall(generic_the_pattern, description_lower)
    if matches:
        # Only flag if there's no quoted specific name nearby
        if "'" not in task_description and '"' not in task_description:
            return True

    return False


def _extract_requirements_from_request(user_request: str) -> List[str]:
    """Extract explicit requirements/constraints from user request.

    This implements the "Requirements Checklist" feature - extracting constraints
    that the plan must address.

    Args:
        user_request: The user's task request

    Returns:
        List of extracted requirement strings
    """
    requirements = []
    request_lower = user_request.lower()

    # Negative constraints (things to avoid)
    negative_patterns = [
        (r"(?:do\s+)?not\s+duplicate", "Avoid duplicating existing functionality"),
        (r"without\s+(?:any\s+)?duplicate", "Avoid duplicating existing functionality"),
        (r"no\s+duplicate", "Avoid duplicating existing functionality"),
        (r"avoid\s+duplicate", "Avoid duplicating existing functionality"),
        (r"don't\s+(?:re)?create", "Do not recreate existing implementations"),
        (r"skip\s+existing", "Skip items that already exist"),
    ]

    # Positive constraints (things to include)
    positive_patterns = [
        (r"add\s+(?:them\s+)?to\s+(?:the\s+)?(\w+)", r"Add items to \1"),
        (r"register\s+(?:them\s+)?(?:in|with)\s+(?:the\s+)?(\w+)", r"Register items in \1"),
        (r"include\s+(?:them\s+)?in\s+(?:the\s+)?(\w+)", r"Include items in \1"),
        (r"update\s+(?:the\s+)?(\w+)\s+(?:to\s+include|with)", r"Update \1 with new items"),
        (r"(?:matrix|config|registry)\s*(?:recipes?)?", "Update configuration/registry with new items"),
    ]

    # Check negative patterns
    for pattern, requirement in negative_patterns:
        if re.search(pattern, request_lower):
            if requirement not in requirements:
                requirements.append(requirement)

    # Check positive patterns
    for pattern, requirement_template in positive_patterns:
        match = re.search(pattern, request_lower)
        if match:
            if r"\1" in requirement_template:
                # Template with capture group
                requirement = re.sub(r"\\1", match.group(1) if match.lastindex else "", requirement_template)
            else:
                requirement = requirement_template
            if requirement not in requirements:
                requirements.append(requirement)

    # Check for explicit test requirements
    if any(word in request_lower for word in ["test", "tests", "testing", "unit test"]):
        requirements.append("Include tests for new functionality")

    # Check for documentation requirements
    if any(word in request_lower for word in ["document", "documentation", "readme", "docstring"]):
        requirements.append("Include documentation updates")

    return requirements


def _recursive_breakdown(task_description: str, action_type: str, context: str, max_depth: int = 2, current_depth: int = 0, tools: list = None, force_breakdown: bool = False) -> List[Dict[str, Any]]:
    """Recursively break down a complex task into subtasks.

    Args:
        task_description: Description of the complex task
        action_type: Type of action
        context: Repository and system context
        max_depth: Maximum recursion depth
        current_depth: Current recursion level
        tools: List of available tools for LLM function calling
        force_breakdown: If True, force breakdown regardless of depth

    Returns:
        List of subtask dictionaries
    """
    if current_depth >= max_depth and not force_breakdown:
        # Max depth reached, return original task
        return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]

    # Add extra instructions when force breakdown is enabled
    force_instruction = ""
    if force_breakdown:
        force_instruction = """
IMPORTANT: This task was detected as overly broad and MUST be broken down into MANY granular subtasks.
- Create at least 5-10 specific subtasks
- Each subtask should be a single, atomic action
- If this involves multiple features/items, create a SEPARATE subtask for EACH one
- Do NOT return a single catch-all subtask
"""

    messages = [
        {"role": "system", "content": BREAKDOWN_SYSTEM},
        {"role": "user", "content": f"""Break down this complex task into smaller subtasks:

Task: {task_description}
Action Type: {action_type}
{force_instruction}
Context:
{context}

Provide detailed subtasks."""}
    ]

    response = ollama_chat(messages, tools=tools) or {}
    if not isinstance(response, dict):
        return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]

    if "error" in response:
        # Fallback to original task if breakdown fails
        return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]

    try:
        content = response.get("message", {}).get("content", "")
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            subtasks = json.loads(json_match.group(0))

            # If force_breakdown is True but we got too few subtasks, try harder
            if force_breakdown and len(subtasks) <= 2:
                print(f"  ⚠️  Breakdown returned only {len(subtasks)} subtasks, retrying with stronger prompt...")
                retry_messages = [
                    {"role": "system", "content": BREAKDOWN_SYSTEM},
                    {"role": "user", "content": f"""The previous breakdown was insufficient. Break down this task into MORE specific subtasks:

Task: {task_description}

REQUIREMENTS:
- You MUST return at least 5 subtasks
- Each subtask must be a SINGLE action (e.g., "Add SMA indicator" not "Add indicators")
- If the task mentions multiple items (analysts, features, etc.), create ONE subtask per item
- Start with review/analysis tasks, then implementation tasks, then test tasks

Example for "add multiple modules/features":
[
  {{"description": "Review existing implementations to understand patterns", "action_type": "review", "complexity": "low"}},
  {{"description": "Add first new module/feature", "action_type": "add", "complexity": "low"}},
  {{"description": "Add second new module/feature", "action_type": "add", "complexity": "low"}},
  {{"description": "Add third new module/feature", "action_type": "add", "complexity": "low"}},
  {{"description": "Add fourth new module/feature", "action_type": "add", "complexity": "low"}},
  {{"description": "Add fifth new module/feature", "action_type": "add", "complexity": "low"}},
  {{"description": "Write unit tests for new modules", "action_type": "add", "complexity": "low"}},
  {{"description": "Update configuration/registry with new modules", "action_type": "edit", "complexity": "low"}}
]

Context:
{context}

Return ONLY a JSON array with at least 5 subtasks."""}
                ]
                retry_response = ollama_chat(retry_messages, tools=tools) or {}
                if isinstance(retry_response, dict) and "error" not in retry_response:
                    retry_content = retry_response.get("message", {}).get("content", "")
                    retry_match = re.search(r'\[.*\]', retry_content, re.DOTALL)
                    if retry_match:
                        retry_subtasks = json.loads(retry_match.group(0))
                        if len(retry_subtasks) > len(subtasks):
                            subtasks = retry_subtasks
                            print(f"  ✓ Retry produced {len(subtasks)} subtasks")

            # Recursively break down any high-complexity subtasks
            expanded_subtasks = []
            for subtask in subtasks:
                if subtask.get("complexity") == "high":
                    # Recursively break down
                    nested = _recursive_breakdown(
                        subtask["description"],
                        subtask["action_type"],
                        context,
                        max_depth,
                        current_depth + 1,
                        tools
                    )
                    expanded_subtasks.extend(nested)
                else:
                    expanded_subtasks.append(subtask)
            return expanded_subtasks
        else:
            return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]
    except Exception as e:
        print(f"  Warning: Could not break down task: {e}")
        return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]


def _ensure_test_and_doc_coverage(plan: ExecutionPlan, user_request: str) -> None:
    """Ensure that the execution plan contains appropriate test and doc tasks.

    This is a deterministic safety net on top of the LLM's planning to guarantee
    that code changes are accompanied by tests and documentation.

    Args:
        plan: The execution plan to validate and augment
        user_request: The user's original request
    """
    has_code_change = any(
        t.action_type in {"edit", "add"} for t in plan.tasks
    )
    has_test_task = any(t.action_type == "test" for t in plan.tasks)

    if has_code_change and not has_test_task:
        # Simple fallback: append a generic test task
        plan.add_task(
            description="Run automated tests relevant to the recent code changes",
            action_type="test",
        )

    # Optionally: look for doc tasks as well
    has_doc_task = any(t.action_type == "doc" for t in plan.tasks)
    if has_code_change and not has_doc_task:
        # Only add doc task for non-trivial changes
        if len([t for t in plan.tasks if t.action_type in {"edit", "add"}]) > 2:
            plan.add_task(
                description="Update documentation / README to reflect code changes",
                action_type="doc",
            )


def _cap_plan_tasks(plan: ExecutionPlan, max_plan_tasks: Optional[int]) -> int:
    """Apply deterministic post-processing to keep plans within task limits.

    Args:
        plan: Execution plan with tasks populated
        max_plan_tasks: Maximum allowed tasks (None disables capping)

    Returns:
        The original task count before capping
    """

    if not max_plan_tasks or len(plan.tasks) <= max_plan_tasks:
        return len(plan.tasks)

    original_count = len(plan.tasks)
    print(
        f"→ Plan exceeds max of {max_plan_tasks} tasks (got {original_count}); merging validation tasks and trimming."
    )

    lint_keywords = ["lint", "ruff", "flake8", "format", "black", "isort", "mypy", "type check"]
    test_keywords = ["pytest", "test", "unit test", "integration test", "coverage", "radon"]
    low_value_actions = {"doc", "test", "review", "general"}

    merged_lint = False
    merged_tests = False
    kept_tasks: List[Task] = []

    for task in plan.tasks:
        text = task.description.lower()
        if any(keyword in text for keyword in lint_keywords):
            merged_lint = True
            continue
        if any(keyword in text for keyword in test_keywords):
            merged_tests = True
            continue
        kept_tasks.append(task)

    protected_tasks = set()
    if merged_lint:
        lint_task = Task(
            "Run lint/format/type checks and address findings",
            action_type="test",
        )
        protected_tasks.add(lint_task)
        kept_tasks.append(lint_task)

    if merged_tests:
        test_task = Task(
            "Run automated tests (pytest/coverage) and resolve failures",
            action_type="test",
        )
        protected_tasks.add(test_task)
        kept_tasks.append(test_task)

    while len(kept_tasks) > max_plan_tasks:
        removed = False
        for idx in range(len(kept_tasks) - 1, -1, -1):
            task = kept_tasks[idx]
            if task in protected_tasks:
                continue
            if task.action_type in low_value_actions:
                kept_tasks.pop(idx)
                removed = True
                break
        if not removed:
            kept_tasks.pop()

    for idx, task in enumerate(kept_tasks):
        task.task_id = idx

    plan.tasks = kept_tasks
    print(f"  → Final task count after capping: {len(plan.tasks)}")
    return original_count


def planning_mode(
    user_request: str,
    enable_advanced_analysis: bool = True,
    enable_recursive_breakdown: bool = True,
    coding_mode: bool = False,
    max_plan_tasks: Optional[int] = None,
    max_planning_iterations: Optional[int] = None,
) -> ExecutionPlan:
    """Generate execution plan from user request with advanced analysis.

    This function analyzes the user's request and repository context to create
    a comprehensive execution plan with tasks, dependencies, risk levels, and
    validation steps.

    Args:
        user_request: The user's task request
        enable_advanced_analysis: Enable dependency, impact, and risk analysis
        enable_recursive_breakdown: Enable recursive breakdown of complex tasks
        coding_mode: Enable coding-specific planning (ensures test/doc tasks)

    Returns:
        ExecutionPlan with comprehensive task breakdown and analysis
    """
    print("=" * 60)
    print("PLANNING MODE")
    print("=" * 60)

    task_limit = max_plan_tasks or MAX_PLAN_TASKS
    planning_iterations_limit = max_planning_iterations or MAX_PLANNING_TOOL_ITERATIONS
    model_name = config.PLANNING_MODEL
    model_supports_tools = config.PLANNING_SUPPORTS_TOOLS

    # Get available tools for LLM function calling
    tools = get_available_tools()

    # Get system and repository context
    print("→ Analyzing system and repository...")
    sys_info = get_system_info_cached()
    context = get_repo_context()

    ensure_escape_is_cleared("Planning interrupted")

    # Format available tools for the planning prompt
    tools_description = _format_available_tools(tools)

    # Build system prompt with optional coding suffix
    system_prompt = PLANNING_SYSTEM
    if coding_mode:
        system_prompt += CODING_PLANNING_SUFFIX

    # Enhanced system prompt with available tools
    enhanced_system_prompt = f"""{system_prompt}

AVAILABLE TOOLS AND CAPABILITIES:
{tools_description}

Use these tools when planning to:
- Search for relevant code patterns
- Analyze security vulnerabilities
- Detect memory issues, buffer overflows, use-after-free
- Run static analysis tools
- Verify file existence before planning modifications
"""

    token_guidance = (
        "TOKEN BUDGET: Keep replies tight (aim for <=1,200 tokens). "
        "If the task needs more, ask for a target token count or propose splitting into multiple smaller planning passes. "
        f"Never exceed the ~{MAX_LLM_TOKENS_PER_RUN:,} token conversation budget; prefer multiple iterations over one long response."
    )
    plan_size_guidance = (
        f"PLAN SIZE LIMIT: Produce at most {task_limit} tasks. Group validation actions (lint, mypy, tests, coverage) into 1–2 tasks near the end. "
        "Avoid creating separate incremental test/lint loops unless explicitly requested."
    )

    messages = [
        {"role": "system", "content": enhanced_system_prompt},
        {"role": "user", "content": f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

Repository context:
{context}

User request:
{user_request}

{token_guidance}

{plan_size_guidance}

CRITICAL REQUIREMENTS:
- You MUST generate AT LEAST 2 distinct tasks (minimum)
- NEVER return a single task that just restates the user request
- Break down work into phases: review/analysis → implementation → testing/validation

INSTRUCTIONS:
1. If you need context, call 1-3 tools maximum (list_dir, search_code, or read_file)
2. Then IMMEDIATELY generate the execution plan as a JSON array
3. For unknown details, create review/research tasks in the plan instead of calling more tools
4. Prefer creating review tasks over exhaustive exploration

GUIDELINES:
- For structural changes: consider searching for existing patterns, OR create a review task
- For multi-file work: consider calling list_dir once, OR create a review task to identify files
- Avoid calling multiple tools repeatedly - gather minimal context then generate the plan
- If uncertain, create a "Review existing X" task rather than exploring further

MINIMUM ACCEPTABLE PLAN STRUCTURE:
[
  {{"description": "Review existing code/patterns relevant to request", "action_type": "review", "complexity": "low"}},
  {{"description": "Implement specific change/feature", "action_type": "add", "complexity": "medium"}},
  {{"description": "Run tests to validate changes", "action_type": "test", "complexity": "low"}}
]

Generate a comprehensive execution plan as a JSON array NOW with AT LEAST 2 tasks."""}
    ]

    print("→ Generating execution plan...")
    print(f"  Plan task cap: {task_limit} | Planning tool-iterations cap: {planning_iterations_limit}")
    ensure_escape_is_cleared("Planning interrupted before LLM call")
    response = _call_llm_with_tools(
        messages,
        tools,
        max_iterations=planning_iterations_limit,
        model_name=model_name,
        model_supports_tools=model_supports_tools,
    )
    ensure_escape_is_cleared("Planning interrupted")

    if not isinstance(response, dict):
        error_msg = "Planning failed: LLM returned no response"
        print(f"Error: {error_msg}")
        raise RuntimeError(error_msg)

    if "error" in response:
        error_msg = f"Planning failed: {response['error']}"
        print(f"Error: {error_msg}")
        raise RuntimeError(error_msg)

    # Parse the plan
    plan = ExecutionPlan()
    try:
        content = response.get("message", {}).get("content", "")
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            tasks_data = json.loads(json_match.group(0))

            # Check if recursive breakdown is needed
            if enable_recursive_breakdown:
                print("→ Checking for complex tasks...")
                expanded_tasks = []

                # Detect single/few broad tasks that need forced breakdown
                is_single_broad_plan = (
                    len(tasks_data) <= 2 and
                    any(_is_overly_broad_task(t.get("description", ""), user_request) for t in tasks_data)
                )

                if is_single_broad_plan:
                    print("  ⚠️  Detected overly broad plan with 1-2 tasks - forcing breakdown...")

                for task_data in tasks_data:
                    complexity = task_data.get("complexity", "low")
                    description = task_data.get("description", "")

                    # Force breakdown for broad tasks when plan is too small
                    should_breakdown = (
                        complexity == "high" or
                        (is_single_broad_plan and _is_overly_broad_task(description, user_request))
                    )

                    if should_breakdown:
                        print(f"  ├─ Breaking down {'broad' if is_single_broad_plan else 'complex'} task: {description[:60]}...")
                        subtasks = _recursive_breakdown(
                            description,
                            task_data.get("action_type", "general"),
                            context,
                            max_depth=2,
                            current_depth=0,
                            tools=tools,
                            force_breakdown=is_single_broad_plan
                        )
                        print(f"     └─ Expanded into {len(subtasks)} subtasks")
                        expanded_tasks.extend(subtasks)
                    else:
                        expanded_tasks.append(task_data)
                tasks_data = expanded_tasks

            # VAGUE PLACEHOLDER DETECTION: Check for tasks with abstract placeholders
            print("→ Validating task specificity...")
            vague_task_count = 0
            for task_data in tasks_data:
                description = task_data.get("description", "")
                if _has_vague_placeholder(description):
                    vague_task_count += 1
                    print(f"  ⚠️  Vague task detected: '{description[:60]}...'")

            if vague_task_count > 0:
                print(f"  ⚠️  {vague_task_count} task(s) contain vague placeholders - adding discovery task")
                # Prepend a discovery task if we have vague tasks
                discovery_task = {
                    "description": f"Scan and identify specific classes/functions to implement for: {user_request[:100]}",
                    "action_type": "review",
                    "complexity": "low"
                }
                # Only add if not already present
                has_discovery = any(
                    "scan" in t.get("description", "").lower() and "identify" in t.get("description", "").lower()
                    for t in tasks_data
                )
                if not has_discovery:
                    tasks_data.insert(0, discovery_task)

            # REQUIREMENTS CHECKLIST: Extract and validate requirements
            requirements = _extract_requirements_from_request(user_request)
            if requirements:
                print(f"→ Extracted {len(requirements)} requirement(s) from user request:")
                for req in requirements:
                    print(f"   - {req}")

                # Check if requirements are covered in the plan
                missing_requirements = []
                for req in requirements:
                    req_lower = req.lower()
                    covered = False
                    for task_data in tasks_data:
                        desc_lower = task_data.get("description", "").lower()
                        # Check for keyword overlap
                        req_keywords = set(req_lower.split())
                        desc_keywords = set(desc_lower.split())
                        if len(req_keywords & desc_keywords) >= 2:
                            covered = True
                            break
                    if not covered:
                        missing_requirements.append(req)

                if missing_requirements:
                    print(f"  ⚠️  {len(missing_requirements)} requirement(s) may not be covered in plan:")
                    for missing in missing_requirements:
                        print(f"     - {missing}")
                        # Add a task for the missing requirement
                        tasks_data.append({
                            "description": f"Ensure: {missing}",
                            "action_type": "review" if "avoid" in missing.lower() else "edit",
                            "complexity": "low"
                        })

            # Add all tasks to plan
            for task_data in tasks_data:
                plan.add_task(
                    task_data.get("description", "Unknown task"),
                    task_data.get("action_type", "general")
                )
                # Set complexity on the task
                if len(plan.tasks) > 0:
                    plan.tasks[-1].complexity = task_data.get("complexity", "low")
        else:
            print("Warning: Could not parse JSON plan, using fallback")
            # Fallback: split into review + implementation
            plan.add_task(f"Review existing code and patterns for: {user_request}", "review")
            plan.add_task(user_request, "general")
    except Exception as e:
        print(f"Warning: Error parsing plan: {e}")
        # Fallback: split into review + implementation
        plan.add_task(f"Review existing code and patterns for: {user_request}", "review")
        plan.add_task(user_request, "general")

    # CRITICAL VALIDATION: Ensure we have at least 2 tasks
    if len(plan.tasks) == 1:
        print("  ⚠️  Plan contains only 1 task - forcing split into review + implementation")
        single_task = plan.tasks[0]
        plan.tasks = []

        # Create review task
        plan.add_task(
            f"Review existing code, patterns, and implementations relevant to: {single_task.description}",
            "review"
        )
        plan.tasks[-1].complexity = "low"

        # Keep original task as implementation
        plan.add_task(
            single_task.description,
            single_task.action_type if single_task.action_type != "general" else "add"
        )
        plan.tasks[-1].complexity = single_task.complexity

        # Add test task if it's a code change
        if plan.tasks[-1].action_type in {"add", "edit"}:
            plan.add_task(
                "Run automated tests to validate the changes",
                "test"
            )
            plan.tasks[-1].complexity = "low"

    original_task_count = len(plan.tasks)
    capped_from = _cap_plan_tasks(plan, task_limit)
    if not plan.tasks:
        raise RuntimeError("Planning produced zero tasks after applying task limits")

    if capped_from > len(plan.tasks):
        print(f"→ Tasks capped from {capped_from} to {len(plan.tasks)} (max {task_limit})")
    else:
        print(f"→ Final task count: {len(plan.tasks)} (max {task_limit})")

    # Advanced planning analysis
    if enable_advanced_analysis and len(plan.tasks) > 0:
        print("\n→ Performing advanced planning analysis...")

        # 1. Dependency Analysis
        print("  ├─ Analyzing task dependencies...")
        dep_analysis = plan.analyze_dependencies()

        # 2. Risk Evaluation for each task
        print("  ├─ Evaluating risks...")
        high_risk_tasks = []
        for task in plan.tasks:
            task.risk_level = plan.evaluate_risk(task)
            if task.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                high_risk_tasks.append(task)

        # 3. Impact Assessment
        print("  ├─ Assessing impact scope...")
        for task in plan.tasks:
            impact = plan.assess_impact(task)
            task.impact_scope = impact.get("affected_files", []) + impact.get("affected_modules", [])
            task.estimated_changes = len(task.impact_scope)

        # 4. Generate Rollback Plans for risky tasks
        print("  ├─ Creating rollback plans...")
        for task in plan.tasks:
            if task.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]:
                task.rollback_plan = plan.create_rollback_plan(task)

        # 5. Generate Validation Steps
        print("  └─ Generating validation steps...")
        for task in plan.tasks:
            task.validation_steps = plan.generate_validation_steps(task)

    # Ensure test/doc coverage for coding workflows
    if coding_mode and len(plan.tasks) > 0:
        print("\n→ Ensuring test and documentation coverage...")
        _ensure_test_and_doc_coverage(plan, user_request)

    # Derive and set goals for goal-oriented execution
    if len(plan.tasks) > 0:
        print("→ Deriving execution goals...")
        try:
            from rev.models.goal import derive_goals_from_request
            task_types = list(set(t.action_type for t in plan.tasks))
            plan.goals = derive_goals_from_request(user_request, task_types)
            print(f"  ✓ {len(plan.goals)} goal(s) derived")
        except Exception as e:
            print(f"  ⚠ Could not derive goals: {e}")

    # Display plan
    print("\n" + "=" * 60)
    print("EXECUTION PLAN")
    print("=" * 60)
    for i, task in enumerate(plan.tasks, 1):
        risk_emoji = {
            RiskLevel.LOW: "🟢",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.HIGH: "🟠",
            RiskLevel.CRITICAL: "🔴"
        }.get(task.risk_level, "⚪")

        print(f"{i}. [{task.action_type.upper()}] {task.description}")

        if enable_advanced_analysis:
            print(f"   Risk: {risk_emoji} {task.risk_level.value.upper()}", end="")
            if task.risk_reasons:
                print(f" ({task.risk_reasons[0]})")
            else:
                print()

            if task.dependencies:
                dep_desc = [f"#{d+1}" for d in task.dependencies]
                print(f"   Depends on: {', '.join(dep_desc)}")

            if task.breaking_change:
                print("   ⚠️  Warning: Potentially breaking change")

    print("=" * 60)

    # Display analysis summary
    if enable_advanced_analysis:
        print("\n" + "=" * 60)
        print("PLANNING ANALYSIS SUMMARY")
        print("=" * 60)

        # Risk summary
        risk_counts = {}
        for level in RiskLevel:
            count = sum(1 for t in plan.tasks if t.risk_level == level)
            if count > 0:
                risk_counts[level] = count

        print(f"Total tasks: {len(plan.tasks)}")
        print(f"Risk distribution:")
        # Use dict for risk ordering to handle unknown values gracefully
        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        for level, count in sorted(risk_counts.items(), key=lambda x: risk_order.get(x[0].value, 999)):
            emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(level.value, "⚪")
            print(f"  {emoji} {level.value.upper()}: {count}")

        # Dependency insights
        if dep_analysis["parallelization_potential"] > 0:
            print(f"\n⚡ Parallelization potential: {dep_analysis['parallelization_potential']} tasks can run concurrently")
            print(f"   Critical path length: {dep_analysis['critical_path_length']} steps")

        # High-risk warnings
        critical_tasks = [t for t in plan.tasks if t.risk_level == RiskLevel.CRITICAL]
        high_risk_tasks = [t for t in plan.tasks if t.risk_level == RiskLevel.HIGH]

        if critical_tasks:
            print(f"\n🔴 CRITICAL: {len(critical_tasks)} high-risk task(s) require extra caution")
            for task in critical_tasks:
                print(f"   - Task #{task.task_id + 1}: {task.description[:60]}...")
                if task.rollback_plan:
                    print(f"     Rollback plan available")

        if high_risk_tasks:
            print(f"\n🟠 WARNING: {len(high_risk_tasks)} task(s) have elevated risk")

        # Goals summary
        if plan.goals:
            print(f"\n🎯 GOALS ({len(plan.goals)}):")
            for goal in plan.goals:
                if hasattr(goal, 'description'):
                    print(f"   - {goal.description}")
                    if hasattr(goal, 'metrics'):
                        print(f"     Metrics: {len(goal.metrics)}")

        print("=" * 60)

    return plan
