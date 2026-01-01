import json
from typing import Any, Optional
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output

KEYWORD_SNIPPET_PATTERNS = [
    "register",
    "inspect.getmembers",
    "pkgutil",
    "importlib",
    "registry",
]


def _extract_snippet(tool_name: str, tool_args: dict, raw_result: Any) -> str:
    """Return a relevant snippet for read_file/read_file_lines outputs."""
    try:
        text = raw_result if isinstance(raw_result, str) else str(raw_result)
    except Exception:
        return str(raw_result)[:500]

    def _keyword_window(txt: str) -> Optional[str]:
        lines = txt.splitlines()
        for idx, line in enumerate(lines):
            if any(k.lower() in line.lower() for k in KEYWORD_SNIPPET_PATTERNS):
                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)
                return "\n".join(lines[start:end])
        return None

    if tool_name in {"read_file", "read_file_lines"}:
        if "...[truncated]..." in text or len(text) > 5000:
            try:
                path = tool_args.get("path") if isinstance(tool_args, dict) else None
                include = path if isinstance(path, str) else "**/*"
                search = execute_tool(
                    "search_code",
                    {"pattern": "register|pkgutil|importlib|getmembers|registry", "include": include, "regex": True},
                    agent_name="AnalysisAgent",
                )
                payload = json.loads(search) if isinstance(search, str) else {}
                matches = payload.get("matches") or []
                if matches:
                    m = matches[0]
                    file = m.get("file")
                    line = m.get("line")
                    if file and isinstance(line, int):
                        window = execute_tool(
                            "read_file_lines",
                            {"path": file, "start": max(1, line - 3), "end": line + 3},
                            agent_name="AnalysisAgent",
                        )
                        if isinstance(window, str) and window.strip():
                            return window
            except Exception:
                pass
        kw = _keyword_window(text)
        if kw:
            return kw
    return text[:500]

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
        """Execute an analysis task."""

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
            'read_file', 'read_file_lines', 'search_code', 'list_dir', 'get_file_info',
            'mcp_list_servers', 'mcp_call_tool',
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

                    # Unwrap nested {"arguments": {...}} payloads that some recoveries return.
                    if not error_type and isinstance(arguments, dict) and "arguments" in arguments and not any(
                        k in arguments for k in ("path", "paths")
                    ):
                        inner = arguments.get("arguments")
                        if isinstance(inner, dict):
                            arguments = inner

                    if not error_type:
                        print(f"  -> AnalysisAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments, agent_name="AnalysisAgent")

                        snippet = _extract_snippet(tool_name, arguments, result)
                        context.add_insight("analysis_agent", f"task_{task.task_id}_analysis", {
                            "tool": tool_name,
                            "summary": snippet
                        })
                        return build_subagent_output(
                            agent_name="AnalysisAgent",
                            tool_name=tool_name,
                            tool_args=arguments,
                            tool_output=result,
                            context=context,
                            task_id=task.task_id,
                        )

            # If we reach here, there was an error
            if error_type:
                if error_type in {"text_instead_of_tool_call", "empty_tool_calls", "missing_tool_calls"}:
                    retried = False
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=[t["function"]["name"] for t in get_available_tools()],
                    )
                    if not recovered:
                        recovered = recover_tool_call_from_text_lenient(
                            response.get("message", {}).get("content", ""),
                            allowed_tools=[t["function"]["name"] for t in get_available_tools()],
                        )
                        if recovered:
                            print("  [WARN] AnalysisAgent: using lenient tool call recovery from text output")
                    if not recovered:
                        recovered = retry_tool_call_with_response_format(
                            messages,
                            available_tools,
                            allowed_tools=[t["function"]["name"] for t in get_available_tools()],
                        )
                        if recovered:
                            retried = True
                            print(f"  -> Retried tool call with JSON format: {recovered.name}")
                    if recovered:
                        if not recovered.name:
                            return self.make_failure_signal("missing_tool", "Recovered tool call missing name")
                        if not recovered.arguments:
                            return self.make_failure_signal("missing_tool_args", "Recovered tool call missing arguments")
                        if not retried:
                            print(f"  -> Recovered tool call from text output: {recovered.name}")
                        tool_args = recovered.arguments
                        if (
                            recovered.name == "read_file"
                            and isinstance(tool_args, dict)
                            and isinstance(tool_args.get("paths"), list)
                        ):
                            outputs = {}
                            for path in tool_args.get("paths", []):
                                if not isinstance(path, str):
                                    continue
                                outputs[path] = execute_tool("read_file", {"path": path}, agent_name="AnalysisAgent")
                            raw_result = json.dumps(outputs)
                        else:
                            raw_result = execute_tool(recovered.name, tool_args, agent_name="AnalysisAgent")

                        snippet = _extract_snippet(recovered.name, tool_args, raw_result)
                        context.add_insight("analysis_agent", f"task_{task.task_id}_analysis", {
                            "tool": recovered.name,
                            "summary": snippet
                        })
                        return build_subagent_output(
                            agent_name="AnalysisAgent",
                            tool_name=recovered.name,
                            tool_args=tool_args,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

                print(f"  -> AnalysisAgent: {error_detail}")

                # Check if we should attempt recovery
                if self.should_attempt_recovery(task, context):
                    print(f"  -> Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide clearer analysis instructions."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"AnalysisAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in AnalysisAgent: {e}"
            print(f"  -> {error_msg}")

            # Request recovery for exceptions
            if self.should_attempt_recovery(task, context):
                print(f"  -> Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during analysis",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
