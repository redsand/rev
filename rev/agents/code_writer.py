import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

CODE_WRITER_SYSTEM_PROMPT = """You are a specialized Code Writer agent. Your sole purpose is to execute a single coding task by calling the appropriate tool (`write_file` or `replace_in_file`).

You will be given a task description and context about the repository. Analyze them carefully.

CRITICAL RULES:
1.  You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2.  Based on the task, decide whether to create a new file (`write_file`) or modify an existing one (`replace_in_file`).
3.  If using `replace_in_file`, you MUST provide the *exact* `old_string` content to be replaced, including all original indentation and surrounding lines for context. Use the provided file content to construct this.
4.  Ensure the `new_string` is complete and correctly indented to match the surrounding code.
5.  If creating a new file, ensure the full file content is provided to the `write_file` tool.
6.  Your response MUST be a single, valid JSON object representing the tool call.

Example for `replace_in_file`:
{
  "tool_name": "replace_in_file",
  "arguments": {
    "file_path": "path/to/file.py",
    "old_string": "...\nline to be replaced\n...",
    "new_string": "...\nnew line of code\n..."
  }
}

Example for `write_file`:
{
  "tool_name": "write_file",
  "arguments": {
    "file_path": "path/to/new_file.py",
    "content": "full content of the new file"
  }
}

Now, generate the tool call to complete the user's request.
"""

class CodeWriterAgent(BaseAgent):
    """
    A sub-agent that specializes in writing and editing code.
    Implements intelligent error recovery with retry limits.
    """

    # Max retries for this agent (prevents infinite loops)
    MAX_RECOVERY_ATTEMPTS = 2

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a code writing or editing task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"CodeWriterAgent executing task: {task.description}")

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file']]

        messages = [
            {"role": "system", "content": CODE_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        # Track recovery attempts for this specific task
        # Use task_id to track per-task recovery (important for continuous multi-task execution)
        recovery_key = f"code_writer_recovery_{task.task_id}"
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
                        print(f"  → CodeWriterAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)
                        return result

            # If we reach here, there was an error
            if error_type:
                print(f"  ⚠️ CodeWriterAgent: {error_detail}")

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
                    context.add_error(f"CodeWriterAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return f"[FINAL_FAILURE] {error_type}: {error_detail}"

        except Exception as e:
            error_msg = f"Exception in CodeWriterAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            # Request recovery for exceptions
            if recovery_attempts < self.MAX_RECOVERY_ATTEMPTS:
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts + 1}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during code writing",
                    detailed_reason=str(e)
                )
                return f"[RECOVERY_REQUESTED] Exception: {e}"
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return f"[FINAL_FAILURE] {error_msg}"