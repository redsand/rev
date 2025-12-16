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
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a tool creation task by calling an LLM to generate a tool file.
        """
        print(f"ToolCreationAgent executing task: {task.description}")

        # For tool creation, we mainly need write_file
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

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"ToolCreationAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"ToolCreationAgent: {error_reason}")
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
                    error_msg = f"ToolCreationAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                    context.add_error(error_msg)
                    self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                    return error_msg

            print(f"  → ToolCreationAgent will call tool '{tool_name}' with arguments: {arguments}")

            result = execute_tool(tool_name, arguments)

            # Store info about created tool
            if tool_name == "write_file" and "file_path" in arguments:
                context.add_insight("tool_creation_agent", f"task_{task.task_id}_created", {
                    "tool_file": arguments["file_path"],
                    "created": True
                })

            return result

        except Exception as e:
            error_msg = f"Error executing task in ToolCreationAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg
