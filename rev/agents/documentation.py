import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

DOCUMENTATION_SYSTEM_PROMPT = """You are a specialized Documentation agent. Your purpose is to create, update, and review documentation for code, APIs, and projects.

You will be given a task description and context about the repository. Analyze them carefully.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Based on the task, decide what documentation to create or update:
   - Code documentation: Docstrings, inline comments
   - API documentation: Endpoint descriptions, parameters, examples
   - User documentation: README, guides, tutorials
   - Developer documentation: Architecture, contributing guidelines
3. Use appropriate tools:
   - `write_file` to create new documentation files (README.md, docs/*.md)
   - `replace_in_file` to update existing documentation or add docstrings
   - `read_file` to examine existing code/docs before updating
4. If using `replace_in_file`, you MUST provide the *exact* `old_string` content to be replaced.
5. Follow documentation best practices:
   - Clear, concise language
   - Examples and use cases
   - Proper formatting (Markdown, reStructuredText, etc.)
   - Complete parameter descriptions
   - Return value descriptions
   - Exception documentation
6. Your response MUST be a single, valid JSON object representing the tool call.

DOCUMENTATION PATTERNS:
- Python docstrings: Google, NumPy, or Sphinx style
- Markdown: Headers, code blocks, lists, tables
- API docs: Endpoint, method, parameters, response, examples
- README: Purpose, installation, usage, contributing, license
- Code comments: WHY not WHAT (explain intent, not mechanics)

Example for adding docstring:
{
  "tool_name": "replace_in_file",
  "arguments": {
    "file_path": "path/to/file.py",
    "old_string": "def calculate_total(items, tax_rate):\n    subtotal = sum(item.price for item in items)\n    return subtotal * (1 + tax_rate)",
    "new_string": "def calculate_total(items: List[Item], tax_rate: float) -> float:\n    \"\"\"Calculate the total price including tax.\n    \n    Args:\n        items: List of Item objects with price attributes.\n        tax_rate: Tax rate as a decimal (e.g., 0.08 for 8%).\n    \n    Returns:\n        Total price including tax.\n    \n    Example:\n        >>> items = [Item(price=10.0), Item(price=20.0)]\n        >>> calculate_total(items, 0.08)\n        32.4\n    \"\"\"\n    subtotal = sum(item.price for item in items)\n    return subtotal * (1 + tax_rate)"
  }
}

Example for creating README:
{
  "tool_name": "write_file",
  "arguments": {
    "file_path": "README.md",
    "content": "# Project Name\\n\\n## Description\\n\\nBrief description...\\n\\n## Installation\\n\\n```bash\\npip install package\\n```\\n\\n## Usage\\n\\nExample usage..."
  }
}

Now, generate the tool call to complete the documentation request.
"""

class DocumentationAgent(BaseAgent):
    """
    A sub-agent that specializes in creating and updating documentation.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a documentation task by calling an LLM to generate a tool call.
        """
        print(f"DocumentationAgent executing task: {task.description}")

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file']]

        messages = [
            {"role": "system", "content": DOCUMENTATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"DocumentationAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"DocumentationAgent: {error_reason}")
                self.request_replan(context, "LLM produced no tool calls", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_call = tool_calls[0]
            tool_name = tool_call['function']['name']
            arguments_str = tool_call['function']['arguments']

            if isinstance(arguments_str, dict):
                arguments = arguments_str
            else:
                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError:
                    error_msg = f"DocumentationAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                    context.add_error(error_msg)
                    self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                    return error_msg

            print(f"  → DocumentationAgent will call tool '{tool_name}' with arguments: {arguments}")

            result = execute_tool(tool_name, arguments)
            return result

        except Exception as e:
            error_msg = f"Error executing task in DocumentationAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg
