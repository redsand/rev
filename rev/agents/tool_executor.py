import json
import shlex
from typing import Any, Dict, Optional, Tuple

from rev.agents.base import BaseAgent
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.llm.client import ollama_chat
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools


TOOL_EXECUTOR_SYSTEM_PROMPT = """You are a specialized Tool Execution agent.

You will be given a task that should be completed by calling an EXISTING tool from the tool registry.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Do NOT create new tools. If no existing tool can do the job, call `request_replanning` with a suggestion to use [CREATE_TOOL] instead.
3. Prefer purpose-built tools over shell commands. Avoid `run_cmd` unless absolutely necessary.
4. Your response MUST be a single, valid JSON object representing the tool call.

COORDINATION TOOLS (use these when the task cannot be completed with a normal tool):
- `request_replanning`: When the current plan/approach won't work and a different strategy is needed.
- `request_research`: When you need more codebase context before you can act effectively.
- `request_user_guidance`: When facing ambiguity that requires human decision-making.
- `inject_tasks`: When you discover prerequisite steps missing from the plan.
- `escalate_strategy`: When the current approach has failed and a fundamentally different method is needed.
- `add_insight`: When you discover something other agents should know about.
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
            if self._is_meta_tool(tool_name):
                return self._handle_meta_tool(context, tool_name, tool_args)
            if tool_name in allowed_tool_names:
                raw_result = execute_tool(tool_name, tool_args, agent_name="ToolExecutorAgent")
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
                if "error" in response:
                    error_type = "llm_error_payload"
                    error_detail = str(response.get("error"))
                else:
                    error_type = "missing_message_key"
                    error_detail = f"Response missing 'message' key: {list(response.keys())}"
            elif "tool_calls" not in response["message"]:
                content = response.get("message", {}).get("content", "") or ""
                recovered = recover_tool_call_from_text(content, allowed_tools=tool_names)
                if not recovered:
                    recovered = recover_tool_call_from_text_lenient(content, allowed_tools=tool_names)
                    if recovered:
                        print("  [WARN] ToolExecutorAgent: using lenient tool call recovery from text output")
                if recovered:
                    if self._is_meta_tool(recovered.name):
                        return self._handle_meta_tool(context, recovered.name, recovered.arguments or {})
                    raw_result = execute_tool(recovered.name, recovered.arguments, agent_name="ToolExecutorAgent")
                    return build_subagent_output(
                        agent_name="ToolExecutorAgent",
                        tool_name=recovered.name,
                        tool_args=recovered.arguments,
                        tool_output=raw_result,
                        context=context,
                        task_id=task.task_id,
                    )
                recovered = retry_tool_call_with_response_format(
                    messages,
                    selected_tools,
                    allowed_tools=tool_names,
                )
                if recovered:
                    if self._is_meta_tool(recovered.name):
                        return self._handle_meta_tool(context, recovered.name, recovered.arguments or {})
                    raw_result = execute_tool(recovered.name, recovered.arguments, agent_name="ToolExecutorAgent")
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
                        if self._is_meta_tool(tool_name):
                            return self._handle_meta_tool(context, tool_name, tool_args)
                        if tool_name not in allowed_tool_names:
                            error_type = "unknown_tool"
                            error_detail = f"Tool '{tool_name}' is not available"
                        else:
                            raw_result = execute_tool(tool_name, tool_args, agent_name="ToolExecutorAgent")
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
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=[t for t in allowed_tool_names if isinstance(t, str)],
                    )
                    if not recovered:
                        recovered = recover_tool_call_from_text_lenient(
                            response.get("message", {}).get("content", ""),
                            allowed_tools=[t for t in allowed_tool_names if isinstance(t, str)],
                        )
                        if recovered:
                            print("  [WARN] ToolExecutorAgent: using lenient tool call recovery from text output")
                    if not recovered:
                        recovered = retry_tool_call_with_response_format(
                            messages,
                            selected_tools,
                            allowed_tools=[t for t in allowed_tool_names if isinstance(t, str)],
                        )
                        if recovered:
                            retried = True
                            print(f"  -> Retried tool call with JSON format: {recovered.name}")
                    if recovered:
                        if not recovered.name:
                            return self.make_failure_signal("missing_tool", "Recovered tool call missing name")
                        if not recovered.arguments:
                            return self.make_failure_signal("missing_tool_args", "Recovered tool call missing arguments")
                        if self._is_meta_tool(recovered.name):
                            return self._handle_meta_tool(context, recovered.name, recovered.arguments or {})
                        if not retried:
                            print(f"  -> Recovered tool call from text output: {recovered.name}")
                        raw_result = execute_tool(recovered.name, recovered.arguments, agent_name="ToolExecutorAgent")
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

    # -- Meta-tool names that trigger agent coordination instead of normal execution --
    _META_TOOLS = {
        "request_replanning", "request_research", "request_user_guidance",
        "inject_tasks", "escalate_strategy", "add_insight",
    }

    def _is_meta_tool(self, tool_name: str) -> bool:
        """Check if this is a meta/coordination tool handled by the agent."""
        return tool_name in self._META_TOOLS

    def _handle_meta_tool(self, context: RevContext, tool_name: str, args: dict) -> str:
        """Dispatch a meta-tool call to the appropriate agent coordination mechanism."""
        handler = {
            "request_replanning": self._handle_replanning,
            "request_research": self._handle_research,
            "request_user_guidance": self._handle_user_guidance,
            "inject_tasks": self._handle_inject_tasks,
            "escalate_strategy": self._handle_escalate_strategy,
            "add_insight": self._handle_add_insight,
        }.get(tool_name)
        if handler:
            return handler(context, args)
        return self.make_failure_signal("unknown_meta_tool", f"No handler for meta-tool '{tool_name}'")

    def _handle_replanning(self, context: RevContext, args: dict) -> str:
        """Handle an LLM request to replan the current task."""
        reason = args.get("reason", "LLM requested replanning")
        suggestion = args.get("suggestion", "")
        detailed = f"{reason}. Suggestion: {suggestion}" if suggestion else reason
        print(f"  -> ToolExecutorAgent: LLM requested replanning: {reason}")
        self.request_replan(context, reason="LLM requested replanning", detailed_reason=detailed)
        return self.make_recovery_request("replanning_requested", detailed)

    def _handle_research(self, context: RevContext, args: dict) -> str:
        """Handle an LLM request for codebase research."""
        query = args.get("query", "")
        reason = args.get("reason", "LLM requested research")
        print(f"  -> ToolExecutorAgent: LLM requested research: {query}")
        self.request_research(context, query=query, reason=reason)
        return self.make_recovery_request("research_requested", f"Research query: {query}")

    def _handle_user_guidance(self, context: RevContext, args: dict) -> str:
        """Handle an LLM request to escalate to user for guidance."""
        question = args.get("question", "LLM needs user guidance")
        options = args.get("options", [])
        detailed = f"Question: {question}"
        if options:
            detailed += f" Options: {', '.join(options)}"
        print(f"  -> ToolExecutorAgent: LLM requesting user guidance: {question}")
        context.add_agent_request("USER_GUIDANCE", {
            "agent": "ToolExecutorAgent",
            "reason": question,
            "guidance": detailed,
        })
        return self.make_recovery_request("user_guidance_requested", detailed)

    def _handle_inject_tasks(self, context: RevContext, args: dict) -> str:
        """Handle an LLM request to inject new tasks into the plan."""
        tasks = args.get("tasks", [])
        reason = args.get("reason", "LLM identified missing tasks")
        print(f"  -> ToolExecutorAgent: LLM injecting {len(tasks)} task(s): {reason}")
        context.add_agent_request("INJECT_TASKS", {
            "tasks": tasks,
        })
        task_descs = [t.get("description", "?") for t in tasks if isinstance(t, dict)]
        return self.make_recovery_request("tasks_injected", f"Injected {len(tasks)} task(s): {'; '.join(task_descs)}")

    def _handle_escalate_strategy(self, context: RevContext, args: dict) -> str:
        """Handle an LLM request to escalate the current strategy."""
        reason = args.get("reason", "LLM requested strategy escalation")
        suggestion = args.get("suggestion", "")
        detailed = f"{reason}. Suggestion: {suggestion}" if suggestion else reason
        print(f"  -> ToolExecutorAgent: LLM escalating strategy: {reason}")
        context.add_agent_request("EDIT_STRATEGY_ESCALATION", {
            "agent": "ToolExecutorAgent",
            "reason": reason,
            "detailed_reason": detailed,
        })
        return self.make_recovery_request("strategy_escalated", detailed)

    def _handle_add_insight(self, context: RevContext, args: dict) -> str:
        """Handle an LLM sharing an insight with other agents."""
        key = args.get("key", "unknown")
        value = args.get("value", "")
        print(f"  -> ToolExecutorAgent: LLM sharing insight: {key}")
        context.add_insight("ToolExecutorAgent", key, value)
        return f"Insight recorded: {key} = {value}"
