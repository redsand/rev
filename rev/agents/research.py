import json
from typing import Any, Optional
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text
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
                        )
                        if isinstance(window, str) and window.strip():
                            return window
            except Exception:
                pass
        kw = _keyword_window(text)
        if kw:
            return kw
    return text[:500]

RESEARCH_SYSTEM_PROMPT = """You are a specialized Research agent. Your purpose is to investigate codebases, gather context, analyze code structures, and provide insights.

You will be given a research task and context about the repository. Your goal is to gather information using available tools.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Use the most appropriate research tool for the task:
   - `read_file` to examine specific files
   - `search_code` for regex-based source searches
   - `rag_search` for semantic/natural-language lookup
   - `list_dir` / `tree_view` to inspect directory layout
   - `analyze_code_structures` to understand code organization
   - `find_symbol_usages` to track symbol usage
   - `analyze_dependencies` to understand module relationships
   - `analyze_code_context` to learn change history and intent
   - `check_structural_consistency` to validate schemas/models
3. Your research should be focused and actionable.
4. Your response MUST be a single, valid JSON object representing the tool call.

PATH VALIDATION (CRITICAL):
- Always check the "Work Completed So Far" and tool outputs in your context.
- If a previous tool (like `split_python_module_classes`) explicitly states it created a file at a specific path, USE THAT EXACT PATH.
- Do NOT guess paths or assume standard locations if the context provides the actual path.
- If you are unsure if a file exists at a path mentioned in the task, use `file_exists` or `get_file_info` before attempting a full `read_file`.

RESEARCH STRATEGIES:
- Code understanding: Read files, analyze structures, find dependencies
- Symbol tracking: Find definitions, usages, and references
- Pattern discovery: Search for similar code, identify conventions
- Impact analysis: Analyze dependencies, find affected code
- Context gathering: Understand WHY code exists, not just WHAT it does

Example for reading a file:
{
  "tool_name": "read_file",
  "arguments": {
    "path": "path/to/file.py"
  }
}

Example for searching code:
{
  "tool_name": "search_code",
  "arguments": {
    "pattern": "def\\s+authenticate",
    "include": "src/**/*.py"
  }
}

Example for listing a directory:
{
  "tool_name": "list_dir",
  "arguments": {
    "pattern": "src/**"
  }
}

Example for analyzing structures:
{
  "tool_name": "analyze_code_structures",
  "arguments": {
    "path": "."
  }
}

Now, generate the tool call to complete the research request.
"""

class ResearchAgent(BaseAgent):
    """
    A sub-agent that specializes in code investigation and context gathering.
    Implements intelligent error recovery with retry limits.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a research task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"ResearchAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        # Get all available tools, focusing on read-only research tools
        all_tools = get_available_tools()
        research_tool_names = [
            'read_file', 'read_file_lines', 'search_code', 'rag_search', 'list_dir', 'tree_view',
            'analyze_code_structures', 'find_symbol_usages', 'analyze_dependencies',
            'analyze_code_context', 'check_structural_consistency', 'get_file_info'
        ]
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=research_tool_names,
            max_tools=7,
        )
        available_tools = selected_tools

        messages = [
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nSelected Context:\n{rendered_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)
            error_type = None
            error_detail = None

            if not response:
                error_type = "empty_response"
                error_detail = "LLM returned None/empty response"
            elif "message" not in response:
                error_type = "missing_message_key"
                error_detail = f"Response missing 'message' key: {list(response.keys())}"
            elif "tool_calls" not in response["message"]:
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
                    # Success path
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

                    # Unwrap nested {"arguments": {...}} payloads when present.
                    if not error_type and isinstance(arguments, dict) and "arguments" in arguments and not any(
                        k in arguments for k in ("path", "paths")
                    ):
                        inner = arguments.get("arguments")
                        if isinstance(inner, dict):
                            arguments = inner

                    if not error_type:
                        print(f"  -> ResearchAgent will call tool '{tool_name}' with arguments: {arguments}")
                        raw_result = execute_tool(tool_name, arguments)

                        snippet = _extract_snippet(tool_name, arguments, raw_result)
                        context.add_insight("research_agent", f"task_{task.task_id}_result", {
                            "tool": tool_name,
                            "result": snippet
                        })

                        return build_subagent_output(
                            agent_name="ResearchAgent",
                            tool_name=tool_name,
                            tool_args=arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

            # Error handling
            if error_type:
                if error_type in {"text_instead_of_tool_call", "empty_tool_calls", "missing_tool_calls"}:
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=[t["function"]["name"] for t in get_available_tools()],
                    )
                    if recovered:
                        print(f"  -> Recovered tool call from text output: {recovered.name}")
                        if (
                            recovered.name == "read_file"
                            and isinstance(recovered.arguments, dict)
                            and isinstance(recovered.arguments.get("paths"), list)
                        ):
                            outputs = {}
                            for path in recovered.arguments.get("paths", []):
                                if not isinstance(path, str):
                                    continue
                                outputs[path] = execute_tool("read_file", {"path": path})
                            raw_result = json.dumps(outputs)
                        else:
                            raw_result = execute_tool(recovered.name, recovered.arguments)
                        snippet = _extract_snippet(recovered.name, recovered.arguments, raw_result)
                        context.add_insight("research_agent", f"task_{task.task_id}_result", {
                            "tool": recovered.name,
                            "result": snippet
                        })
                        return build_subagent_output(
                            agent_name="ResearchAgent",
                            tool_name=recovered.name,
                            tool_args=recovered.arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

                print(f"  [WARN] ResearchAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  -> Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please specify what code or files need to be researched."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"ResearchAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in ResearchAgent: {e}"
            print(f"  [WARN] {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  -> Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during research",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
