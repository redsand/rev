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
   - `search_code` for regex-based source searches
   - `rag_search` for semantic/natural-language lookup
   - `list_dir` / `tree_view` to inspect directory layout
   - `analyze_code_structures` to understand code organization
   - `find_symbol_usages` to track symbol usage
   - `analyze_dependencies` to understand module relationships
   - `analyze_code_context` to learn change history and intent
   - `check_structural_consistency` to validate schemas/models
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
    "path": "path/to/file.py"
  }
}

Example for searching code:
{
  "tool_name": "search_code",
  "arguments": {
    "pattern": "def\\s+authenticate",
    "include": "src/**/*.py"
  }
}

Example for listing a directory:
{
  "tool_name": "list_dir",
  "arguments": {
    "pattern": "src/**"
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
    Implements intelligent error recovery with retry limits.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a research task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"ResearchAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        # Get all available tools, focusing on read-only research tools
        all_tools = get_available_tools()
        research_tool_names = [
            'read_file', 'search_code', 'rag_search', 'list_dir', 'tree_view',
            'analyze_code_structures', 'find_symbol_usages', 'analyze_dependencies',
            'analyze_code_context', 'check_structural_consistency', 'get_file_info'
        ]
        available_tools = [tool for tool in all_tools if tool['function']['name'] in research_tool_names]

        messages = [
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
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
                        print(f"  → ResearchAgent will call tool '{tool_name}' with arguments: {arguments}")
                        result = execute_tool(tool_name, arguments)

                        # Store research findings in context for other agents to use
                        context.add_insight("research_agent", f"task_{task.task_id}_result", {
                            "tool": tool_name,
                            "result": result[:500] if isinstance(result, str) else str(result)[:500]
                        })

                        return result

            # Error handling
            if error_type:
                print(f"  ⚠️ ResearchAgent: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please specify what code or files need to be researched."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"ResearchAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in ResearchAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during research",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
