import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text
from rev.agents.context_provider import build_context_and_tools

ANALYSIS_SYSTEM_PROMPT = """You are a specialized Analysis agent. Your purpose is to perform deep code analysis, identify issues, and provide nuanced feedback and alternative suggestions.

You will be given an analysis task and context about the repository. Your goal is to analyze code quality, security, and design.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Use the most appropriate analysis tool for the task:
   - `scan_security_issues` or `detect_secrets` for security findings
   - `check_license_compliance` / `check_dependency_vulnerabilities` / `check_dependency_updates` for supply-chain risk
   - `analyze_test_coverage` to check test coverage
   - `analyze_semantic_diff` to detect breaking changes
   - `analyze_code_context` to understand code history
   - `run_all_analysis` for a comprehensive static analysis sweep
   - `analyze_code_structures` / `check_structural_consistency` for schema consistency
   - `analyze_runtime_logs`, `analyze_performance_regression`, or `analyze_error_traces` for runtime issues
   - `read_file` when direct inspection is required
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
  "tool_name": "run_all_analysis",
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

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes an analysis task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"AnalysisAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        # Get all available tools, focusing on analysis tools
        all_tools = get_available_tools()
        analysis_tool_names = [
            'scan_security_issues', 'detect_secrets', 'check_license_compliance',
            'check_dependency_vulnerabilities', 'check_dependency_updates',
            'analyze_test_coverage', 'analyze_semantic_diff', 'analyze_code_context',
            'run_all_analysis', 'analyze_code_structures', 'check_structural_consistency',
            'analyze_runtime_logs', 'analyze_performance_regression', 'analyze_error_traces',
            'read_file'
        ]
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=analysis_tool_names,
            max_tools=7,
        )
        available_tools = selected_tools

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nSelected Context:\n{rendered_context}"}
        ]

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
                if error_type == "text_instead_of_tool_call":
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=[t["function"]["name"] for t in available_tools],
                    )
                    if recovered:
                        print(f"  -> Recovered tool call from text output: {recovered.name}")
                        return execute_tool(recovered.name, recovered.arguments)

                print(f"  ⚠️ AnalysisAgent: {error_detail}")

                # Check if we should attempt recovery
                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide clearer analysis instructions."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"AnalysisAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in AnalysisAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            # Request recovery for exceptions
            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during analysis",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
