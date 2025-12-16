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
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a debugging task by calling an LLM to generate a tool call.
        """
        print(f"DebuggingAgent executing task: {task.description}")

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file', 'search_files']]

        messages = [
            {"role": "system", "content": DEBUGGING_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"DebuggingAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"DebuggingAgent: {error_reason}")
                self.request_replan(context, "LLM produced no tool calls", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_call = tool_calls[0]
            tool_name = tool_call['function']['name']
            arguments_str = tool_call['function']['arguments']

            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                error_msg = f"DebuggingAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                context.add_error(error_msg)
                self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                return error_msg

            print(f"  → DebuggingAgent will call tool '{tool_name}' with arguments: {arguments}")

            result = execute_tool(tool_name, arguments)
            return result

        except Exception as e:
            error_msg = f"Error executing task in DebuggingAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg
