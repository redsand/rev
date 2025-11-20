"""
Execution planning mode for generating comprehensive task plans.

This module provides the planning phase functionality that analyzes a user request
and generates a detailed execution plan with task dependency analysis, risk
assessment, and validation steps.
"""

import re
import json
import sys
from typing import Dict, Any

from rev.models.task import ExecutionPlan, RiskLevel, TaskStatus
from rev.llm.client import ollama_chat
from rev.config import get_system_info_cached
from rev.tools.git_ops import get_repo_context


PLANNING_SYSTEM = """You are an expert CI/CD agent analyzing tasks and creating execution plans.

Your job is to:
1. Understand the user's request
2. Analyze the repository structure
3. Create a comprehensive, ordered checklist of tasks

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

Return ONLY a JSON array of tasks in this format:
[
  {"description": "Review current API endpoint structure", "action_type": "review"},
  {"description": "Add error handling to /api/users endpoint", "action_type": "edit"},
  {"description": "Create tests for error cases", "action_type": "add"},
  {"description": "Run test suite to validate changes", "action_type": "test"}
]

Be thorough but concise. Each task should be independently executable."""


def planning_mode(user_request: str, enable_advanced_analysis: bool = True) -> ExecutionPlan:
    """Generate execution plan from user request with advanced analysis.

    This function analyzes the user's request and repository context to create
    a comprehensive execution plan with tasks, dependencies, risk levels, and
    validation steps.

    Args:
        user_request: The user's task request
        enable_advanced_analysis: Enable dependency, impact, and risk analysis

    Returns:
        ExecutionPlan with comprehensive task breakdown and analysis
    """
    print("=" * 60)
    print("PLANNING MODE")
    print("=" * 60)

    # Get system and repository context
    print("→ Analyzing system and repository...")
    sys_info = get_system_info_cached()
    context = get_repo_context()

    messages = [
        {"role": "system", "content": PLANNING_SYSTEM},
        {"role": "user", "content": f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

Repository context:
{context}

User request:
{user_request}

Generate a comprehensive execution plan."""}
    ]

    print("→ Generating execution plan...")
    response = ollama_chat(messages)

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
            for task_data in tasks_data:
                plan.add_task(
                    task_data.get("description", "Unknown task"),
                    task_data.get("action_type", "general")
                )
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

        print("=" * 60)

    return plan
