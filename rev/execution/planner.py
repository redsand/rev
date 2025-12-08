"""
Execution planning mode for generating comprehensive task plans.

This module provides the planning phase functionality that analyzes a user request
and generates a detailed execution plan with task dependency analysis, risk
assessment, and validation steps.
"""

import re
import json
import sys
from typing import Dict, Any, List

from rev.models.task import ExecutionPlan, RiskLevel, TaskStatus
from rev.llm.client import ollama_chat
from rev.config import get_system_info_cached
from rev.tools.git_ops import get_repo_context
from rev.tools.registry import get_available_tools, execute_tool


PLANNING_SYSTEM = """You are an expert CI/CD agent analyzing tasks and creating execution plans.

Your job is to:
1. Understand the user's request
2. USE TOOLS to analyze the repository structure and gather information
3. Create a comprehensive, ordered checklist of tasks based on what you discover

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
4. Based on tool results, create detailed, file-specific tasks

Example for security audit:
- Call list_dir to find all .c and .cpp files
- Call search_code for each unsafe pattern (strcpy, malloc, etc.)
- Create separate tasks for EACH file found
- Add tasks for running security tools (Valgrind, AddressSanitizer, etc.)

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

Given a high-level task, break it down into specific, atomic subtasks that can be executed independently.

You have access to code analysis tools to help understand the codebase:
- analyze_ast_patterns, run_pylint, run_mypy, run_radon_complexity, find_dead_code
- search_code, list_dir, read_file

Consider:
1. What files need to be created or modified?
2. What are the logical steps to implement this?
3. What dependencies exist between steps?
4. What testing is needed?

Return ONLY a JSON array of subtasks:
[
  {"description": "Create authentication middleware file", "action_type": "add", "complexity": "low"},
  {"description": "Implement JWT token validation logic", "action_type": "edit", "complexity": "medium"},
  {"description": "Add authentication tests", "action_type": "add", "complexity": "low"}
]

Keep subtasks focused and executable. Each should accomplish one clear goal."""


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


def _call_llm_with_tools(messages: List[Dict], tools: List[Dict], max_iterations: int = 5) -> Dict[str, Any]:
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
        response = ollama_chat(conversation, tools=tools)

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
    return ollama_chat(conversation, tools=None)  # Final call without tools


def _recursive_breakdown(task_description: str, action_type: str, context: str, max_depth: int = 2, current_depth: int = 0, tools: list = None) -> List[Dict[str, Any]]:
    """Recursively break down a complex task into subtasks.

    Args:
        task_description: Description of the complex task
        action_type: Type of action
        context: Repository and system context
        max_depth: Maximum recursion depth
        current_depth: Current recursion level
        tools: List of available tools for LLM function calling

    Returns:
        List of subtask dictionaries
    """
    if current_depth >= max_depth:
        # Max depth reached, return original task
        return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]

    messages = [
        {"role": "system", "content": BREAKDOWN_SYSTEM},
        {"role": "user", "content": f"""Break down this complex task into smaller subtasks:

Task: {task_description}
Action Type: {action_type}

Context:
{context}

Provide detailed subtasks."""}
    ]

    response = ollama_chat(messages, tools=tools)

    if "error" in response:
        # Fallback to original task if breakdown fails
        return [{"description": task_description, "action_type": action_type, "complexity": "medium"}]

    try:
        content = response.get("message", {}).get("content", "")
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if json_match:
            subtasks = json.loads(json_match.group(0))
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


def planning_mode(
    user_request: str,
    enable_advanced_analysis: bool = True,
    enable_recursive_breakdown: bool = True,
    coding_mode: bool = False
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

    # Get available tools for LLM function calling
    tools = get_available_tools()

    # Get system and repository context
    print("→ Analyzing system and repository...")
    sys_info = get_system_info_cached()
    context = get_repo_context()

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

IMPORTANT: Before creating the execution plan:
1. Use available tools to explore the codebase
2. For security audits: enumerate C/C++ files, search for unsafe functions
3. For multi-file tasks: use list_dir to find all relevant files
4. Call tools as needed to gather information

After gathering information with tools, generate a comprehensive execution plan as a JSON array."""}
    ]

    print("→ Generating execution plan...")
    response = _call_llm_with_tools(messages, tools, max_iterations=30)

    if "error" in response:
        print(f"Error: {response['error']}")
        sys.exit(1)

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
                for task_data in tasks_data:
                    complexity = task_data.get("complexity", "low")
                    if complexity == "high":
                        print(f"  ├─ Breaking down complex task: {task_data['description'][:60]}...")
                        subtasks = _recursive_breakdown(
                            task_data["description"],
                            task_data.get("action_type", "general"),
                            context,
                            max_depth=2,
                            current_depth=0,
                            tools=tools
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
        for level, count in sorted(risk_counts.items(), key=lambda x: ["low", "medium", "high", "critical"].index(x[0].value)):
            emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}[level.value]
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
