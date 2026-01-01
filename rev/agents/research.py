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

STRUCTURE_LIST_KEYWORDS = {
    "list", "listing", "tree", "structure", "layout", "directories", "directory",
    "files", "folders", "project structure", "repo structure", "file structure",
    "show me", "what files", "what folders", "where is",
}

STRUCTURE_DEEP_KEYWORDS = {
    "architecture", "call graph", "dependency graph", "dependencies",
    "class hierarchy", "inheritance", "module relationships", "semantic",
    "analyze code", "analyze structure", "structural consistency",
}


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
                    agent_name="ResearchAgent",
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
                            agent_name="ResearchAgent",
                        )
                        if isinstance(window, str) and window.strip():
                            return window
            except Exception:
                pass
        kw = _keyword_window(text)
        if kw:
            return kw
    return text[:500]


def _is_structure_inventory_task(description: str) -> bool:
    if not description:
        return False
    desc = description.lower()
    if any(keyword in desc for keyword in STRUCTURE_DEEP_KEYWORDS):
        return False
    return any(keyword in desc for keyword in STRUCTURE_LIST_KEYWORDS)


def _pattern_from_path(path: str) -> str:
    if not path:
        return "**/*"
    if any(ch in path for ch in ("*", "?", "[")):
        return path
    trimmed = path.rstrip("/\\")
    if trimmed in ("", "."):
        return "**/*"
    return f"{trimmed}/**"


def _coerce_structure_tool(description: str, tool_name: str, arguments: dict) -> tuple[str, dict, bool]:
    """Prefer list_dir/tree_view over analyze_code_structures for simple listings."""
    if tool_name != "analyze_code_structures":
        return tool_name, arguments, False
    if not _is_structure_inventory_task(description):
        return tool_name, arguments, False

    path = "."
    if isinstance(arguments, dict):
        candidate = arguments.get("path") or arguments.get("directory") or arguments.get("dir")
        if isinstance(candidate, str) and candidate.strip():
            path = candidate.strip()

    desc = (description or "").lower()
    if any(keyword in desc for keyword in ("tree", "structure", "layout", "directory", "directories")):
        return "tree_view", {"path": path, "max_depth": 2}, True
    return "list_dir", {"pattern": _pattern_from_path(path)}, True


def _tool_is_available(tool_name: str, tools: list[dict]) -> bool:
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") or {}
        if fn.get("name") == tool_name:
            return True
    return False

RESEARCH_SYSTEM_PROMPT = """You are a specialized Research agent. Your purpose is to investigate codebases, gather context, analyze code structures, and provide insights.

You will be given a research task and context about the repository. Your goal is to gather information using available tools.

CRITICAL RULES (PERFORMANCE FIX 5 - STRICT JSON ENFORCEMENT):
1. You MUST respond with ONLY a JSON object. NOTHING ELSE.
   - NO explanations before the JSON
   - NO explanations after the JSON
   - NO markdown code blocks (no ```)
   - NO natural language
   - ONLY the raw JSON object
   - Example of CORRECT response:
     {"tool_name": "read_file", "arguments": {"path": "src/app.js"}}
   - Example of WRONG response:
     I'll read the file using read_file.
     {"tool_name": "read_file", "arguments": {"path": "src/app.js"}}
2. Use the provided 'System Information' (OS, Platform, Shell Type) to choose the correct commands and path syntax.
3. Use the most appropriate research tool for the task:
   - `read_file` to examine specific files
   - `search_code` for regex-based source searches
   - `rag_search` for semantic/natural-language lookup
   - `list_dir` / `tree_view` to inspect directory layout (prefer these for structure listings)
   - `analyze_code_structures` to understand code organization (use only for deep analysis)
   - `find_symbol_usages` to track symbol usage
   - `analyze_dependencies` to understand module relationships
   - `analyze_code_context` to learn change history and intent
   - `check_structural_consistency` to validate schemas/models
4. Your research should be focused and actionable.
5. RESPONSE FORMAT (NO EXCEPTIONS): Your ENTIRE response must be ONLY the JSON object. Do not write ANY text outside the JSON. Start your response with { and end with }. Nothing before, nothing after.

CONTEXT AWARENESS (CRITICAL):
- ALWAYS check your context for information before reading files
- Validation output, test results, and error messages are often in previous task results
- NEVER assume file names like "pytest_output.txt" or "validation.log" - these are NOT created by default
- If you need validation/test output, it's in the tool result JSON from previous tasks, not in a separate file
- Only use `read_file` for actual source code files explicitly mentioned in task descriptions
- Before reading ANY file, ask yourself: "Is this information already in my context?"

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

RESPOND NOW WITH ONLY THE JSON OBJECT - NO OTHER TEXT:
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
            'analyze_code_context', 'check_structural_consistency', 'get_file_info',
            'mcp_list_servers', 'mcp_call_tool',
        ]
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=research_tool_names,
            max_tools=30,  # Increased from 7 to allow more comprehensive research
            force_tool_names=["rag_search"],
        )
        available_tools = selected_tools

        if _is_structure_inventory_task(task.description):
            tool_name, arguments, coerced = _coerce_structure_tool(
                task.description,
                "analyze_code_structures",
                {"path": "."},
            )
            if _tool_is_available(tool_name, available_tools):
                if coerced:
                    print(f"  -> ResearchAgent using direct tool '{tool_name}' for structure listing")
                raw_result = execute_tool(tool_name, arguments, agent_name="ResearchAgent")
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

        messages = [
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nSelected Context:\n{rendered_context}"}
        ]

        max_llm_retries = 3
        last_error_type = None
        last_error_detail = None

        for attempt in range(max_llm_retries):
            try:
                response = ollama_chat(messages, tools=available_tools)
                error_type = None
                error_detail = None

                if not response:
                    error_type = "empty_response"
                    error_detail = "LLM returned None/empty response"
                elif "error" in response:
                    error_type = "llm_error"
                    error_detail = response.get("error")
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
                            tool_name, arguments, coerced = _coerce_structure_tool(
                                task.description,
                                tool_name,
                                arguments if isinstance(arguments, dict) else {},
                            )
                            if coerced:
                                print(f"  -> ResearchAgent coerced to cheaper tool '{tool_name}' for structure listing")
                            print(f"  -> ResearchAgent will call tool '{tool_name}' with arguments: {arguments}")
                            raw_result = execute_tool(tool_name, arguments, agent_name="ResearchAgent")

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

                # Error handling inside loop
                if error_type:
                    # Try recovery first
                    if error_type in {"text_instead_of_tool_call", "empty_tool_calls", "missing_tool_calls"}:
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
                                print("  [WARN] ResearchAgent: using lenient tool call recovery from text output")
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
                                    outputs[path] = execute_tool("read_file", {"path": path}, agent_name="ResearchAgent")
                                raw_result = json.dumps(outputs)
                            else:
                                raw_result = execute_tool(recovered.name, recovered.arguments, agent_name="ResearchAgent")
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
                        retry = retry_tool_call_with_response_format(
                            messages,
                            available_tools,
                            allowed_tools=[t["function"]["name"] for t in get_available_tools()],
                        )
                        if retry:
                            print(f"  -> Retried tool call with JSON format: {retry.name}")
                            if (
                                retry.name == "read_file"
                                and isinstance(retry.arguments, dict)
                                and isinstance(retry.arguments.get("paths"), list)
                            ):
                                outputs = {}
                                for path in retry.arguments.get("paths", []):
                                    if not isinstance(path, str):
                                        continue
                                    outputs[path] = execute_tool("read_file", {"path": path}, agent_name="ResearchAgent")
                                raw_result = json.dumps(outputs)
                            else:
                                raw_result = execute_tool(retry.name, retry.arguments, agent_name="ResearchAgent")
                            snippet = _extract_snippet(retry.name, retry.arguments, raw_result)
                            context.add_insight("research_agent", f"task_{task.task_id}_result", {
                                "tool": retry.name,
                                "result": snippet
                            })
                            return build_subagent_output(
                                agent_name="ResearchAgent",
                                tool_name=retry.name,
                                tool_args=retry.arguments,
                                tool_output=raw_result,
                                context=context,
                                task_id=task.task_id,
                            )

                    # If recovery failed, track error and maybe retry
                    last_error_type = error_type
                    last_error_detail = error_detail
                    print(f"  [WARN] ResearchAgent: {error_detail} (attempt {attempt + 1}/{max_llm_retries})")

                    if attempt < max_llm_retries - 1:
                        content = response.get("message", {}).get("content", "") if response else ""
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"SYSTEM: Your last response failed validation ({error_detail}). You MUST respond with a valid JSON tool call."})
                        continue

            except Exception as e:
                error_msg = f"Exception in ResearchAgent: {e}"
                print(f"  [WARN] {error_msg} (attempt {attempt + 1}/{max_llm_retries})")
                last_error_type = "exception"
                last_error_detail = error_msg
                
                if attempt < max_llm_retries - 1:
                    import time
                    time.sleep(1)
                    continue

        # Post-loop failure handling
        if last_error_type:
            if self.should_attempt_recovery(task, context):
                print(f"  -> Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Tool call generation failed",
                    detailed_reason=f"Error type: {last_error_type}. Details: {last_error_detail}. Please specify what code or files need to be researched."
                )
                return self.make_recovery_request(last_error_type, last_error_detail)
            else:
                print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(f"ResearchAgent: {last_error_detail} (after {recovery_attempts} recovery attempts)")
                return self.make_failure_signal(last_error_type, last_error_detail)
        
        return self.make_failure_signal("unknown", "Loop exhausted without specific error")
