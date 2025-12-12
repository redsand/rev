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
    ensure_escape_is_cleared,
    get_system_info_cached,
)
from rev import config
from rev.tools.git_ops import get_repo_context
from rev.tools.registry import get_available_tools, execute_tool


PLANNING_SYSTEM = """You are an expert CI/CD agent analyzing tasks and creating execution plans.

⚠️  CRITICAL PRINCIPLE - REUSE FIRST:
Before creating ANY new file:
1. SEARCH for existing code that solves similar problems
2. PREFER editing/extending existing files over creating new ones
3. ONLY create new files when absolutely necessary
4. AVOID duplication - reuse existing functions, classes, utilities, patterns
5. When creating new files, include justification in task description: "No existing X found - creating new"

TOKEN DISCIPLINE:
- Keep every response concise (aim for <= 1,200 tokens).
- If the request/context would exceed the budget, explicitly ask for a target token cap (e.g., "Plan this in 800 tokens") or propose splitting into smaller batches.
- Prefer breaking large analyses into sequential tool-assisted steps instead of emitting a single giant message.
- Respect the configured maximum conversation budget and surface when additional iterations are safer than one long response.

Your job is to:
1. Understand the user's request
2. USE TOOLS to analyze the repository structure and gather information
3. SEARCH THOROUGHLY for existing code that can be reused or extended
4. Create a comprehensive, ordered checklist that MAXIMIZES code reuse

CRITICAL: You MUST use tools to explore the codebase before planning!

Available tools include:
- analyze_ast_patterns: AST-based pattern matching for Python code
- run_pylint: Comprehensive static code analysis
- run_mypy: Static type checking
- run_radon_complexity: Code complexity metrics
- find_dead_code: Dead code detection
- run_all_analysis: Combined analysis suite
- search_code: Search code using regex patterns
- list_dir: List files matching patterns (use this to enumerate files!)
- read_file: Read file contents
- tree_view: View directory tree structure

PLANNING WORKFLOW:
1. First, use tools to explore (list_dir, search_code, tree_view, read_file)
2. For security audits: enumerate ALL relevant source files, search for unsafe patterns
3. For multi-file changes: list all files that need modification
4. For ANY structural changes: MUST investigate existing structures before creating new ones
5. Based on tool results, create detailed, file-specific tasks

Example for security audit:
- Call list_dir to find all .c and .cpp files
- Call search_code for each unsafe pattern (strcpy, malloc, etc.)
- Create separate tasks for EACH file found
- Add tasks for running security tools (Valgrind, AddressSanitizer, etc.)

Example for structural changes (schemas, types, classes, enums, docs, config):
- Call list_dir to find relevant files (*.prisma, *.ts, *.py, README*, config/*, etc.)
- Call search_code to find ALL existing definitions (enum, class, interface, type, table)
- Call read_file to review existing structures
- Call analyze_code_structures to get comprehensive analysis
- Check for similar or duplicate names
- **MANDATORY: Create tasks to EXTEND/MODIFY existing structures instead of creating new ones**
- Only create new structures if ABSOLUTELY NO suitable existing structure found
- If creating new: Document in task why existing code cannot be reused

IMPORTANT - System Context:
You will be provided with the operating system information. Use this to:
- Choose appropriate shell commands (bash for Linux/Mac, PowerShell for Windows)
- Select platform-specific tools and utilities
- Use correct path separators and file conventions
- Adapt commands to the target environment

Break down the work into atomic tasks:
- Review: Analyze existing code
- Edit: Modify existing files
- Add: Create new files
- Delete: Remove files
- Rename: Move/rename files
- Test: Run tests to validate changes

For COMPLEX requests (e.g., "Add authentication system", "Build payment integration"):
- Break down into HIGH-LEVEL phases first (e.g., "Design", "Implement core", "Add tests", "Documentation")
- Then break each phase into SPECIFIC atomic tasks
- Mark complex tasks with "complexity": "high" to enable recursive breakdown

Return ONLY a JSON array of tasks in this format:
[
  {"description": "Review current API endpoint structure", "action_type": "review", "complexity": "low"},
  {"description": "Add error handling to /api/users endpoint", "action_type": "edit", "complexity": "medium"},
  {"description": "Create tests for error cases", "action_type": "add", "complexity": "low"},
  {"description": "Run test suite to validate changes", "action_type": "test", "complexity": "low"}
]

Complexity levels:
- low: Simple, single-file changes
- medium: Multi-file changes or moderate logic
- high: Major features requiring multiple steps (will be recursively broken down)

Be thorough but concise. Each task should be independently executable."""


CODING_PLANNING_SUFFIX = """
You are planning a CODE + TEST change to this repository.

In addition to the general planning rules above, you MUST:

1. Identify the specific files and modules you will touch.
2. For every non-trivial code change ("edit" or "add"):
   - Add at least one task to CREATE or UPDATE automated tests.
   - Add at least one task to RUN the relevant test command.
3. Prefer many small, atomic tasks over a few large ones.

Use these action_type values:
- "review"  → analyzing existing code or architecture
- "edit"    → modifying existing code
- "add"     → creating new code or tests
- "delete"  → deleting code or files
- "test"    → running tests (pytest, npm test, go test, etc.)
- "doc"     → updating docs, READMEs, or comments

When possible, include hints in the description about:
- which test file or directory is affected
- which test command should be used (e.g. "pytest tests/api", "npm test").

Your goal is to produce a PLAN that explicitly couples code changes with tests and docs.
"""


BREAKDOWN_SYSTEM = """You are an expert at breaking down complex tasks into smaller, actionable subtasks.

Given a high-level task, break it down into SPECIFIC, ATOMIC subtasks that can be executed independently.

CRITICAL RULES FOR BREAKDOWN:
1. Each subtask must be a SINGLE, CONCRETE action (not "implement X, Y, and Z")
2. If the task mentions "many" or "multiple" items, create a SEPARATE subtask for EACH item
3. For integration tasks: first analyze source, then create individual tasks per feature/function
4. Never create a single subtask that encompasses the entire original task
5. Aim for 5-15 granular subtasks for complex integration work
6. Each subtask should take 1-3 tool calls to complete

You have access to code analysis tools to help understand the codebase:
- analyze_ast_patterns, run_pylint, run_mypy, run_radon_complexity, find_dead_code
- search_code, list_dir, read_file

BREAKDOWN STRATEGY:
For "implement features from X to Y" tasks:
1. First: Review/analyze source code to identify specific features
2. For EACH feature found: Create individual implementation subtask
3. After features: Add integration/testing subtasks
4. Never bundle multiple features into one subtask

For "add multiple analysts/indicators/modules":
1. Review existing code to understand patterns
2. One subtask per analyst/indicator to add
3. Separate subtasks for updating registries/configurations
4. Separate subtasks for testing

Return ONLY a JSON array of subtasks:
[
  {"description": "Review existing analysts in lib/analysts.py to understand patterns", "action_type": "review", "complexity": "low"},
  {"description": "Analyze source code in ../external-lib to identify available features", "action_type": "review", "complexity": "low"},
  {"description": "Implement SMA analyst based on identified pattern", "action_type": "add", "complexity": "low"},
  {"description": "Implement EMA analyst based on identified pattern", "action_type": "add", "complexity": "low"},
  {"description": "Implement RSI analyst based on identified pattern", "action_type": "add", "complexity": "low"},
  {"description": "Add unit tests for new analysts", "action_type": "add", "complexity": "low"},
  {"description": "Update matrix recipes configuration", "action_type": "edit", "complexity": "low"}
]

Keep subtasks focused and executable. Each should accomplish ONE clear goal."""


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
                category = "🔍 Memory Analysis"
            elif any(keyword in name for keyword in ["security", "vulnerability", "cve", "scan"]):
                category = "🔒 Security Analysis"
            elif any(keyword in name for keyword in ["pylint", "mypy", "radon", "analysis", "ast"]):
                category = "📊 Static Analysis"
            elif any(keyword in name for keyword in ["mcp", "server"]):
                category = "🔌 MCP Servers"
            elif any(keyword in name for keyword in ["search", "grep", "find", "list", "tree"]):
                category = "🔎 Code Search"
            elif any(keyword in name for keyword in ["read", "write", "file"]):
                category = "📁 File Operations"
            else:
                category = "🛠️  General Tools"

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
        response = ollama_chat(
            conversation,
            tools=tools if (model_supports_tools is not False) else None,
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

        print(f"\n  Planning iteration {iteration + 1}: LLM calling {len(tool_calls)} tool(s)...")

        # Add assistant message with tool calls to conversation
        conversation.append(message)

        # Execute tool calls and get results
        tool_results = _execute_tool_calls(tool_calls)

        # Add tool results to conversation
        conversation.extend(tool_results)

    # Max iterations reached
    print(f"  Warning: Max planning iterations ({max_iterations}) reached")
    final_response = ollama_chat(conversation, tools=None, model=model_name, supports_tools=model_supports_tools) or {}
    if not isinstance(final_response, dict):
        return {"error": "LLM returned no response during planning (final call)"}
    return final_response  # Final call without tools


def _is_overly_broad_task(task_description: str) -> bool:
    """Detect if a task description is too broad and needs breakdown.

    Returns True if the task is likely a high-level request that should be
    broken down into multiple granular subtasks.
    """
    description_lower = task_description.lower()

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

Example for "add multiple indicators":
[
  {{"description": "Review existing indicator implementations", "action_type": "review", "complexity": "low"}},
  {{"description": "Add SMA (Simple Moving Average) indicator", "action_type": "add", "complexity": "low"}},
  {{"description": "Add EMA (Exponential Moving Average) indicator", "action_type": "add", "complexity": "low"}},
  {{"description": "Add RSI (Relative Strength Index) indicator", "action_type": "add", "complexity": "low"}},
  {{"description": "Add MACD indicator", "action_type": "add", "complexity": "low"}},
  {{"description": "Add Bollinger Bands indicator", "action_type": "add", "complexity": "low"}},
  {{"description": "Write unit tests for new indicators", "action_type": "add", "complexity": "low"}},
  {{"description": "Update configuration/registry", "action_type": "edit", "complexity": "low"}}
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
    max_plan_tasks: Optional[int] = None
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

IMPORTANT: Before creating the execution plan:
1. Use available tools to explore the codebase
2. For security audits: enumerate C/C++ files, search for unsafe functions
3. For multi-file tasks: use list_dir to find all relevant files
4. For structural changes: MUST investigate existing definitions first
5. Call tools as needed to gather information

CRITICAL FOR STRUCTURAL CHANGES (schemas, types, classes, docs, config):
- ALWAYS call search_code to find existing definitions:
  * For schemas: search "enum ", "model ", "table ", "CREATE TABLE"
  * For types/classes: search "interface ", "type ", "class ", "struct "
  * For docs: search existing README, documentation structure
  * For config: search existing config files, environment variables
- ALWAYS call list_dir with appropriate patterns:
  * Schemas: *.prisma, schema.*, migrations/*, *.sql
  * Code: *.ts, *.py, *.js, *.go, *.java
  * Docs: README*, docs/*, *.md
  * Config: config/*, .env*, settings.*
- ALWAYS call read_file to understand existing structures
- ALWAYS call analyze_code_structures for comprehensive analysis
- NEVER create new structures without checking if they already exist
- Reuse and extend existing structures whenever possible

After gathering information with tools, generate a comprehensive execution plan as a JSON array."""}
    ]

    print("→ Generating execution plan...")
    ensure_escape_is_cleared("Planning interrupted before LLM call")
    response = _call_llm_with_tools(
        messages,
        tools,
        max_iterations=30,
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
                    any(_is_overly_broad_task(t.get("description", "")) for t in tasks_data)
                )

                if is_single_broad_plan:
                    print("  ⚠️  Detected overly broad plan with 1-2 tasks - forcing breakdown...")

                for task_data in tasks_data:
                    complexity = task_data.get("complexity", "low")
                    description = task_data.get("description", "")

                    # Force breakdown for broad tasks when plan is too small
                    should_breakdown = (
                        complexity == "high" or
                        (is_single_broad_plan and _is_overly_broad_task(description))
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
            plan.add_task(user_request, "general")
    except Exception as e:
        print(f"Warning: Error parsing plan: {e}")
        plan.add_task(user_request, "general")

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
