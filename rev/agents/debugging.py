import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output

DEBUGGING_SYSTEM_PROMPT = """You are a specialized Debugging agent. Your purpose is to locate and fix bugs based on error messages, stack traces, test failures, and other diagnostic inputs.

You will be given a task description (often including error messages or bug reports) and context about the repository.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. First, analyze the bug:
   - Read error messages and stack traces carefully
   - Identify the root cause, not just symptoms
   - Consider edge cases and boundary conditions
3. Then fix the bug using the appropriate tool:
   - Use `replace_in_file` to fix bugs in existing code
   - Use `read_file` if you need to examine more context first
4. If using `replace_in_file`, you MUST provide the *exact* `old_string` content to be replaced.
5. Ensure your fix addresses the root cause and doesn't introduce new bugs.
6. Your response MUST be a single, valid JSON object representing the tool call.

DEBUGGING STRATEGIES:
- Off-by-one errors: Check loop bounds, array indices
- Null/None errors: Add validation and null checks
- Type errors: Ensure correct type conversions
- Logic errors: Verify conditional logic and boolean expressions
- Race conditions: Check for thread safety issues
- Memory leaks: Ensure proper resource cleanup
- Performance issues: Profile and optimize hot paths

Example for fixing a bug:
{
  "tool_name": "replace_in_file",
  "arguments": {
    "file_path": "path/to/buggy_file.py",
    "old_string": "def process_items(items):\n    for i in range(len(items) + 1):\n        print(items[i])",
    "new_string": "def process_items(items):\n    \"\"\"Process all items in the list.\"\"\"\n    for i in range(len(items)):\n        print(items[i])"
  }
}

Example for reading context first:
{
  "tool_name": "read_file",
  "arguments": {
    "file_path": "path/to/file.py"
  }
}

Now, generate the tool call to debug and fix the issue.
"""

class DebuggingAgent(BaseAgent):
    """
    A sub-agent that specializes in locating and fixing bugs.
    Implements intelligent error recovery with retry limits.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """Execute a debugging task."""
        # Focus on identifying root cause and proposing a fix
        recovery_attempts = self.increment_recovery_attempts(task, context)

        allowed_tool_names = [
            'write_file', 'replace_in_file', 'read_file', 'search_code', 'rag_search',
            'mcp_list_servers', 'mcp_call_tool',
        ]
        all_tools = get_available_tools()
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=allowed_tool_names,
            max_tools=5,
            force_tool_names=["rag_search"],
        )
        available_tools = selected_tools

        messages = [
            {"role": "system", "content": DEBUGGING_SYSTEM_PROMPT},
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

                    if not error_type:
                        print(f"  -> DebuggingAgent will call tool '{tool_name}' with arguments: {arguments}")
                        raw_result = execute_tool(tool_name, arguments, agent_name="DebuggingAgent")
                        return build_subagent_output(
                            agent_name="DebuggingAgent",
                            tool_name=tool_name,
                            tool_args=arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

            # Error handling
            if error_type:
                if error_type in {"text_instead_of_tool_call", "empty_tool_calls", "missing_tool_calls"}:
                    retried = False
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=[t["function"]["name"] for t in available_tools],
                    )
                    if not recovered:
                        recovered = recover_tool_call_from_text_lenient(
                            response.get("message", {}).get("content", ""),
                            allowed_tools=[t["function"]["name"] for t in available_tools],
                        )
                        if recovered:
                            print("  [WARN] DebuggingAgent: using lenient tool call recovery from text output")
                    if not recovered:
                        recovered = retry_tool_call_with_response_format(
                            messages,
                            available_tools,
                            allowed_tools=[t["function"]["name"] for t in available_tools],
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
                        raw_result = execute_tool(recovered.name, recovered.arguments, agent_name="DebuggingAgent")
                        return build_subagent_output(
                            agent_name="DebuggingAgent",
                            tool_name=recovered.name,
                            tool_args=recovered.arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

                print(f"  [WARN] DebuggingAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  -> Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide more specific bug details or stack traces."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"DebuggingAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in DebuggingAgent: {e}"
            print(f"  [WARN] {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  -> Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during debugging",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
