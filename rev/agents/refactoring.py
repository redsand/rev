import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

REFACTORING_SYSTEM_PROMPT = """You are a specialized Refactoring agent. Your purpose is to restructure code for improved readability, maintainability, and performance while preserving functionality.

You will be given a task description and context about the repository. Analyze them carefully.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Based on the task, decide whether to modify an existing file (`replace_in_file`) or create a new one (`write_file`).
3. When refactoring, focus on:
   - Improving code readability (clear names, reduced complexity)
   - Enhancing maintainability (DRY principle, separation of concerns)
   - Optimizing performance (algorithmic improvements, resource usage)
   - Preserving existing functionality and tests
4. If using `replace_in_file`, you MUST provide the *exact* `old_string` content to be replaced.
5. Ensure refactored code maintains backward compatibility unless explicitly instructed otherwise.
6. Your response MUST be a single, valid JSON object representing the tool call.

REFACTORING PATTERNS TO APPLY:
- Extract method: Break large functions into smaller, focused ones
- Rename: Use descriptive names for variables, functions, and classes
- Remove duplication: Apply DRY principle
- Simplify conditionals: Reduce nested if-statements, use guard clauses
- Optimize loops: Remove redundant iterations, use appropriate data structures
- Type hints: Add or improve type annotations (Python)
- Documentation: Add/improve docstrings for complex logic

Example for `replace_in_file`:
{
  "tool_name": "replace_in_file",
  "arguments": {
    "file_path": "path/to/file.py",
    "old_string": "def complex_function(x, y):\n    if x > 0:\n        if y > 0:\n            return x + y\n    return 0",
    "new_string": "def calculate_sum_if_positive(x: int, y: int) -> int:\n    \"\"\"Return sum of x and y if both are positive, else 0.\"\"\"\n    if x <= 0 or y <= 0:\n        return 0\n    return x + y"
  }
}

Now, generate the tool call to complete the refactoring request.
"""

class RefactoringAgent(BaseAgent):
    """
    A sub-agent that specializes in code refactoring for improved quality.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a refactoring task by calling an LLM to generate a tool call.
        """
        print(f"RefactoringAgent executing task: {task.description}")

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file']]

        messages = [
            {"role": "system", "content": REFACTORING_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"RefactoringAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"RefactoringAgent: {error_reason}")
                self.request_replan(context, "LLM produced no tool calls", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_call = tool_calls[0]
            tool_name = tool_call['function']['name']
            arguments_str = tool_call['function']['arguments']

            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                error_msg = f"RefactoringAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                context.add_error(error_msg)
                self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                return error_msg

            print(f"  → RefactoringAgent will call tool '{tool_name}' with arguments: {arguments}")

            result = execute_tool(tool_name, arguments)
            return result

        except Exception as e:
            error_msg = f"Error executing task in RefactoringAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg
