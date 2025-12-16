import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

TOOL_CREATION_SYSTEM_PROMPT = """You are a specialized Tool Creation agent. Your purpose is to propose and generate new tools when existing ones are insufficient for a task.

You will be given a task that requires a new tool, and context about the repository and existing tools.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Analyze the task to determine what new tool is needed.
3. Create a Python tool file following this template:
   - Function with clear name and docstring
   - Type hints for all parameters
   - Proper error handling
   - Return value documentation
4. Use `write_file` to create the new tool in the appropriate location (rev/tools/).
5. Your response MUST be a single, valid JSON object representing the tool call.

TOOL CREATION TEMPLATE:
```python
from typing import Dict, Any, List

def new_tool_name(param1: str, param2: int = 0) -> Dict[str, Any]:
    \"\"\"Brief description of what the tool does.

    Args:
        param1: Description of parameter 1
        param2: Description of parameter 2 (default: 0)

    Returns:
        Dictionary containing the tool's results.

    Raises:
        ValueError: If parameters are invalid
    \"\"\"
    try:
        # Tool implementation here
        result = {}

        return {
            "status": "success",
            "data": result
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
```

TOOL CATEGORIES TO CONSIDER:
- File operations: Reading, writing, transforming files
- Code manipulation: AST parsing, code generation
- Analysis: Static analysis, metrics, profiling
- Testing: Test generation, coverage analysis
- Documentation: Doc generation, validation
- Git operations: Branch management, history analysis
- Build/Deploy: CI/CD helpers, deployment scripts

Example for creating a new tool:
{
  "tool_name": "write_file",
  "arguments": {
    "file_path": "rev/tools/custom_analyzer.py",
    "content": "from typing import Dict, Any\\n\\ndef analyze_complexity(file_path: str) -> Dict[str, Any]:\\n    \\\"\\\"\\\"Analyze code complexity.\\n\\n    Args:\\n        file_path: Path to file to analyze\\n\\n    Returns:\\n        Complexity metrics\\n    \\\"\\\"\\\"\\n    # Implementation\\n    return {\\\"complexity\\\": 5}"
  }
}

Now, generate the tool call to create the new tool.
"""

class ToolCreationAgent(BaseAgent):
    """
    An advanced sub-agent that proposes and generates new tools.
    Implements intelligent error recovery with retry limits.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a tool creation task by calling an LLM to generate a tool file.
        Implements error recovery with intelligent retry logic.
        """
        print(f"ToolCreationAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        # For tool creation, we mainly need write_file and read_file
        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'read_file']]

        # Get list of existing tools to provide context
        existing_tools = [tool['function']['name'] for tool in get_available_tools()]
        existing_tools_context = f"\n\nExisting tools: {', '.join(existing_tools[:20])}"  # First 20 tools

        messages = [
            {"role": "system", "content": TOOL_CREATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}{existing_tools_context}"}
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
                        print(f"  → ToolCreationAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)

                        # Store info about created tool
                        if tool_name == "write_file" and "file_path" in arguments:
                            context.add_insight("tool_creation_agent", f"task_{task.task_id}_created", {
                                "tool_file": arguments["file_path"],
                                "created": True
                            })

                        return result

            # Error handling
            if error_type:
                print(f"  ⚠️ ToolCreationAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please specify what tool needs to be created with clear purpose and functionality."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"ToolCreationAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in ToolCreationAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during tool creation",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
