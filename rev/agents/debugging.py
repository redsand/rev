import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

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
        """
        Executes a debugging task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"DebuggingAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        allowed_tool_names = ['write_file', 'replace_in_file', 'read_file', 'search_code', 'rag_search']
        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in allowed_tool_names]

        messages = [
            {"role": "system", "content": DEBUGGING_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
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
                        print(f"  → DebuggingAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)
                        return result

            # Error handling
            if error_type:
                print(f"  ⚠️ DebuggingAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide more specific bug details or stack traces."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"DebuggingAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in DebuggingAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during debugging",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
