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
    Implements intelligent error recovery with retry limits.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a refactoring task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"RefactoringAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file']]

        messages = [
            {"role": "system", "content": REFACTORING_SYSTEM_PROMPT},
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
                        print(f"  → RefactoringAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)
                        return result

            # Error handling
            if error_type:
                print(f"  ⚠️ RefactoringAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide clearer refactoring instructions."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"RefactoringAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in RefactoringAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during refactoring",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
