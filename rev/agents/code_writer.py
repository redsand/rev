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
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a code writing or editing task by calling an LLM to generate a tool call.
        """
        print(f"CodeWriterAgent executing task: {task.description}")

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file']]

        messages = [
            {"role": "system", "content": CODE_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)
            
            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"CodeWriterAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"CodeWriterAgent: {error_reason}")
                self.request_replan(context, "LLM produced no tool calls", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_call = tool_calls[0]
            tool_name = tool_call['function']['name']
            arguments_str = tool_call['function']['arguments']
            
            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                error_msg = f"CodeWriterAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                context.add_error(error_msg)
                self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                return error_msg

            print(f"  → CodeWriterAgent will call tool '{tool_name}' with arguments: {arguments}")
            
            result = execute_tool(tool_name, arguments)
            return result

        except Exception as e:
            error_msg = f"Error executing task in CodeWriterAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg