import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

RESEARCH_SYSTEM_PROMPT = """You are a specialized Research agent. Your purpose is to investigate codebases, gather context, analyze code structures, and provide insights.

You will be given a research task and context about the repository. Your goal is to gather information using available tools.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Use the most appropriate research tool for the task:
   - `read_file` to examine specific files
   - `search_files` to find files matching patterns
   - `grep_files` to search for code patterns
   - `analyze_code_structures` to understand code organization
   - `find_symbol_usages` to track symbol usage
   - `analyze_dependencies` to understand module relationships
3. Your research should be focused and actionable.
4. Your response MUST be a single, valid JSON object representing the tool call.

RESEARCH STRATEGIES:
- Code understanding: Read files, analyze structures, find dependencies
- Symbol tracking: Find definitions, usages, and references
- Pattern discovery: Search for similar code, identify conventions
- Impact analysis: Analyze dependencies, find affected code
- Context gathering: Understand WHY code exists, not just WHAT it does

Example for reading a file:
{
  "tool_name": "read_file",
  "arguments": {
    "file_path": "path/to/file.py"
  }
}

Example for searching files:
{
  "tool_name": "search_files",
  "arguments": {
    "pattern": "*.py",
    "path": "src/"
  }
}

Example for analyzing structures:
{
  "tool_name": "analyze_code_structures",
  "arguments": {
    "path": "."
  }
}

Now, generate the tool call to complete the research request.
"""

class ResearchAgent(BaseAgent):
    """
    A sub-agent that specializes in code investigation and context gathering.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a research task by calling an LLM to generate a tool call.
        """
        print(f"ResearchAgent executing task: {task.description}")

        # Get all available tools, focusing on read-only research tools
        all_tools = get_available_tools()
        research_tool_names = [
            'read_file', 'search_files', 'grep_files', 'list_directory',
            'analyze_code_structures', 'find_symbol_usages', 'analyze_dependencies',
            'analyze_code_context', 'check_structural_consistency'
        ]
        available_tools = [tool for tool in all_tools if tool['function']['name'] in research_tool_names]

        messages = [
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"ResearchAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"ResearchAgent: {error_reason}")
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
                    error_msg = f"ResearchAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                    context.add_error(error_msg)
                    self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                    return error_msg

            print(f"  → ResearchAgent will call tool '{tool_name}' with arguments: {arguments}")

            result = execute_tool(tool_name, arguments)

            # Store research findings in context for other agents to use
            context.add_insight("research_agent", f"task_{task.task_id}_result", {
                "tool": tool_name,
                "result": result[:500] if isinstance(result, str) else str(result)[:500]  # Store first 500 chars
            })

            return result

        except Exception as e:
            error_msg = f"Error executing task in ResearchAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg
