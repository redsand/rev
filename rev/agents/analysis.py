import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

ANALYSIS_SYSTEM_PROMPT = """You are a specialized Analysis agent. Your purpose is to perform deep code analysis, identify issues, and provide nuanced feedback and alternative suggestions.

You will be given an analysis task and context about the repository. Your goal is to analyze code quality, security, and design.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Use the most appropriate analysis tool for the task:
   - `scan_security_issues` to find security vulnerabilities
   - `analyze_test_coverage` to check test coverage
   - `analyze_semantic_diff` to detect breaking changes
   - `analyze_code_context` to understand code history
   - `run_static_analysis` to run comprehensive code analysis
   - `read_file` to examine specific files for analysis
3. Focus on actionable insights and concrete recommendations.
4. Your response MUST be a single, valid JSON object representing the tool call.

ANALYSIS FOCUS AREAS:
- Security: Vulnerabilities, injection risks, insecure APIs
- Quality: Code smells, complexity, maintainability
- Testing: Coverage gaps, missing test cases
- Performance: Bottlenecks, inefficient algorithms
- Design: Architecture issues, coupling, cohesion
- Breaking changes: API changes, backward compatibility

Example for security scan:
{
  "tool_name": "scan_security_issues",
  "arguments": {
    "paths": ["."],
    "severity_threshold": "MEDIUM"
  }
}

Example for test coverage:
{
  "tool_name": "analyze_test_coverage",
  "arguments": {
    "path": ".",
    "show_untested": true
  }
}

Example for static analysis:
{
  "tool_name": "run_static_analysis",
  "arguments": {
    "path": "."
  }
}

Now, generate the tool call to complete the analysis request.
"""

class AnalysisAgent(BaseAgent):
    """
    A sub-agent that specializes in code analysis and review.
    Implements intelligent error recovery with retry limits.
    """

    # Max retries for this agent (prevents infinite loops)
    MAX_RECOVERY_ATTEMPTS = 2

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes an analysis task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"AnalysisAgent executing task: {task.description}")

        # Get all available tools, focusing on analysis tools
        all_tools = get_available_tools()
        analysis_tool_names = [
            'scan_security_issues', 'analyze_test_coverage', 'analyze_semantic_diff',
            'analyze_code_context', 'run_static_analysis', 'check_structural_consistency',
            'read_file', 'analyze_code_structures'
        ]
        available_tools = [tool for tool in all_tools if tool['function']['name'] in analysis_tool_names]

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        # Track recovery attempts for this specific task
        # Use task_id to track per-task recovery (important for continuous multi-task execution)
        recovery_key = f"analysis_recovery_{task.task_id}"
        recovery_attempts = context.get_agent_state(recovery_key, 0)
        context.set_agent_state(recovery_key, recovery_attempts + 1)

        try:
            response = ollama_chat(messages, tools=available_tools)
            error_type = None
            error_detail = None

            # Debug: Print what we got back
            if not response:
                error_type = "empty_response"
                error_detail = "LLM returned None/empty response"
            elif "message" not in response:
                error_type = "missing_message_key"
                error_detail = f"Response missing 'message' key: {list(response.keys())}"
            elif "tool_calls" not in response["message"]:
                # Check if there's regular content instead
                if "content" in response["message"]:
                    error_type = "text_instead_of_tool_call"
                    error_detail = f"LLM returned text instead of tool call: {response['message']['content'][:200]}"
                else:
                    error_type = "missing_tool_calls"
                    error_detail = f"Response missing 'tool_calls': {list(response['message'].keys())}"
            else:
                tool_calls = response["message"]["tool_calls"]
                if not tool_calls:
                    error_type = "empty_tool_calls"
                    error_detail = "tool_calls array is empty"
                else:
                    # Success - process tool call
                    tool_call = tool_calls[0]
                    tool_name = tool_call['function']['name']
                    arguments_str = tool_call['function']['arguments']

                    if isinstance(arguments_str, dict):
                        arguments = arguments_str
                    else:
                        try:
                            arguments = json.loads(arguments_str)
                        except json.JSONDecodeError:
                            error_type = "invalid_json"
                            error_detail = f"Invalid JSON in tool arguments: {arguments_str[:200]}"

                    if not error_type:
                        print(f"  → AnalysisAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)

                        # Store analysis findings in context
                        context.add_insight("analysis_agent", f"task_{task.task_id}_analysis", {
                            "tool": tool_name,
                            "summary": result[:500] if isinstance(result, str) else str(result)[:500]
                        })
                        return result

            # If we reach here, there was an error
            if error_type:
                print(f"  ⚠️ AnalysisAgent: {error_detail}")

                # Check if we should attempt recovery
                if recovery_attempts < self.MAX_RECOVERY_ATTEMPTS:
                    print(f"  → Requesting replan (attempt {recovery_attempts + 1}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide clearer task instructions."
                    )
                    return f"[RECOVERY_REQUESTED] {error_type}: {error_detail}"
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"AnalysisAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return f"[FINAL_FAILURE] {error_type}: {error_detail}"

        except Exception as e:
            error_msg = f"Exception in AnalysisAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            # Request recovery for exceptions
            if recovery_attempts < self.MAX_RECOVERY_ATTEMPTS:
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts + 1}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during analysis",
                    detailed_reason=str(e)
                )
                return f"[RECOVERY_REQUESTED] Exception: {e}"
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return f"[FINAL_FAILURE] {error_msg}"
