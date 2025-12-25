import json
import shlex
from typing import Any, Dict, Optional, Tuple

from rev.agents.base import BaseAgent
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.llm.client import ollama_chat
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools


TOOL_EXECUTOR_SYSTEM_PROMPT = """You are a specialized Tool Execution agent.

You will be given a task that should be completed by calling an EXISTING tool from the tool registry.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Do NOT create new tools. If no existing tool can do the job, request replanning to use [CREATE_TOOL] instead.
3. Prefer purpose-built tools over shell commands. Avoid `run_cmd` unless absolutely necessary.
4. Your response MUST be a single, valid JSON object representing the tool call.
"""


def _parse_cli_style_invocation(text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Parse a CLI-like tool invocation: `tool_name --arg value --flag`."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or stripped.startswith("{") or stripped.startswith("["):
        return None

    try:
        tokens = shlex.split(stripped, posix=False)
    except ValueError:
        return None

    if not tokens:
        return None

    tool_name = tokens[0].strip()
    if not tool_name:
        return None

    args: Dict[str, Any] = {}
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--") and len(token) > 2:
            keyval = token[2:]
            if "=" in keyval:
                key, value = keyval.split("=", 1)
                if key:
                    args[key] = value
                i += 1
                continue

            key = keyval
            # flag-style arg at end or followed by another flag
            if i + 1 >= len(tokens) or tokens[i + 1].startswith("--"):
                args[key] = True
                i += 1
                continue

            args[key] = tokens[i + 1]
            i += 2
            continue

        # Ignore positional tokens we can't safely map.
        i += 1

    return tool_name, args


class ToolExecutorAgent(BaseAgent):
    """Executes existing tools (distinct from ToolCreationAgent)."""

    def execute(self, task: Task, context: RevContext) -> str:
        """Execute a tool task."""
        # Find which tool to run based on the description or context

        recovery_attempts = self.increment_recovery_attempts(task, context)

        all_tools = get_available_tools()
        allowed_tool_names = {
            t.get("function", {}).get("name")
            for t in all_tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
        }

        parsed = _parse_cli_style_invocation(task.description or "")
        if parsed:
            tool_name, tool_args = parsed
            if tool_name in allowed_tool_names:
                raw_result = execute_tool(tool_name, tool_args)
                return build_subagent_output(
                    agent_name="ToolExecutorAgent",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_output=raw_result,
                    context=context,
                    task_id=task.task_id,
                )

        # Fall back to an LLM-produced tool call (tool_calls API), with recovery from text JSON.
        tool_names = [t for t in allowed_tool_names if isinstance(t, str)]
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=tool_names,
            max_tools=7,
        )

        messages = [
            {"role": "system", "content": TOOL_EXECUTOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nSelected Context:\n{rendered_context}"},
        ]

        try:
            response = ollama_chat(messages, tools=selected_tools)
            error_type = None
            error_detail = None

            if not response:
                error_type = "empty_response"
                error_detail = "LLM returned None/empty response"
            elif "message" not in response:
                error_type = "missing_message_key"
                error_detail = f"Response missing 'message' key: {list(response.keys())}"
            elif "tool_calls" not in response["message"]:
                content = response.get("message", {}).get("content", "") or ""
                recovered = retry_tool_call_with_response_format(
                    messages,
                    selected_tools,
                    allowed_tools=tool_names,
                )
                if recovered:
                    raw_result = execute_tool(recovered.name, recovered.arguments)
                    return build_subagent_output(
                        agent_name="ToolExecutorAgent",
                        tool_name=recovered.name,
                        tool_args=recovered.arguments,
                        tool_output=raw_result,
                        context=context,
                        task_id=task.task_id,
                    )

                recovered = recover_tool_call_from_text(content, allowed_tools=tool_names)
                if recovered:
                    raw_result = execute_tool(recovered.name, recovered.arguments)
                    return build_subagent_output(
                        agent_name="ToolExecutorAgent",
                        tool_name=recovered.name,
                        tool_args=recovered.arguments,
                        tool_output=raw_result,
                        context=context,
                        task_id=task.task_id,
                    )
                error_type = "missing_tool_calls"
                error_detail = f"Response missing 'tool_calls': {list(response['message'].keys())}"
            else:
                tool_calls = response["message"]["tool_calls"]
                if not tool_calls:
                    error_type = "empty_tool_calls"
                    error_detail = "tool_calls array is empty"
                else:
                    tool_call = tool_calls[0]
                    tool_name = tool_call["function"]["name"]
                    arguments_str = tool_call["function"]["arguments"]

                    if isinstance(arguments_str, dict):
                        tool_args = arguments_str
                    else:
                        try:
                            tool_args = json.loads(arguments_str)
                        except json.JSONDecodeError:
                            error_type = "invalid_json"
                            error_detail = f"Invalid JSON in tool arguments: {str(arguments_str)[:200]}"

                    if not error_type:
                        if tool_name not in allowed_tool_names:
                            error_type = "unknown_tool"
                            error_detail = f"Tool '{tool_name}' is not available"
                        else:
                            raw_result = execute_tool(tool_name, tool_args)
                            return build_subagent_output(
                                agent_name="ToolExecutorAgent",
                                tool_name=tool_name,
                                tool_args=tool_args,
                                tool_output=raw_result,
                                context=context,
                                task_id=task.task_id,
                            )

            if error_type:
                if error_type in {"text_instead_of_tool_call", "empty_tool_calls", "missing_tool_calls"}:
                    retried = False
                    recovered = retry_tool_call_with_response_format(
                        messages,
                        selected_tools,
                        allowed_tools=[t for t in allowed_tool_names if isinstance(t, str)],
                    )
                    if recovered:
                        retried = True
                        print(f"  -> Retried tool call with JSON format: {recovered.name}")
                    else:
                        recovered = recover_tool_call_from_text(
                            response.get("message", {}).get("content", ""),
                            allowed_tools=[t for t in allowed_tool_names if isinstance(t, str)],
                        )
                    if recovered:
                        if not recovered.name:
                            return self.make_failure_signal("missing_tool", "Recovered tool call missing name")
                        if not recovered.arguments:
                            return self.make_failure_signal("missing_tool_args", "Recovered tool call missing arguments")
                        if not retried:
                            print(f"  -> Recovered tool call from text output: {recovered.name}")
                        raw_result = execute_tool(recovered.name, recovered.arguments)
                        return build_subagent_output(
                            agent_name="ToolExecutorAgent",
                            tool_name=recovered.name,
                            tool_args=recovered.arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

                print(f"  ?? ToolExecutorAgent: {error_detail}")
                if self.should_attempt_recovery(task, context):
                    self.request_replan(
                        context,
                        reason="Tool execution failed",
                        detailed_reason=f"{error_type}: {error_detail}",
                    )
                    return self.make_recovery_request(error_type, error_detail)
                context.add_error(f"ToolExecutorAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in ToolExecutorAgent: {e}"
            print(f"  ?? {error_msg}")
            if self.should_attempt_recovery(task, context):
                self.request_replan(context, reason="Exception during tool execution", detailed_reason=str(e))
                return self.make_recovery_request("exception", str(e))
            context.add_error(error_msg)
            return self.make_failure_signal("exception", error_msg)
