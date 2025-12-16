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
    Implements intelligent error recovery with retry limits.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a documentation task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"DocumentationAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file']]

        messages = [
            {"role": "system", "content": DOCUMENTATION_SYSTEM_PROMPT},
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
                        print(f"  → DocumentationAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)
                        return result

            # Error handling
            if error_type:
                print(f"  ⚠️ DocumentationAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please specify what documentation needs to be created or updated."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"DocumentationAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in DocumentationAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during documentation",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
