import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext

ANALYSIS_SYSTEM_PROMPT = """You are a specialized Analysis agent. Your purpose is to perform deep code analysis, identify issues, and provide nuanced feedback and alternative suggestions.

You will be given an analysis task and context about the repository. Your goal is to analyze code quality, security, and design.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Use the most appropriate analysis tool for the task:
   - `scan_security_issues` to find security vulnerabilities
   - `analyze_test_coverage` to check test coverage
   - `analyze_semantic_diff` to detect breaking changes
   - `analyze_code_context` to understand code history
   - `run_static_analysis` to run comprehensive code analysis
   - `read_file` to examine specific files for analysis
3. Focus on actionable insights and concrete recommendations.
4. Your response MUST be a single, valid JSON object representing the tool call.

ANALYSIS FOCUS AREAS:
- Security: Vulnerabilities, injection risks, insecure APIs
- Quality: Code smells, complexity, maintainability
- Testing: Coverage gaps, missing test cases
- Performance: Bottlenecks, inefficient algorithms
- Design: Architecture issues, coupling, cohesion
- Breaking changes: API changes, backward compatibility

Example for security scan:
{
  "tool_name": "scan_security_issues",
  "arguments": {
    "paths": ["."],
    "severity_threshold": "MEDIUM"
  }
}

Example for test coverage:
{
  "tool_name": "analyze_test_coverage",
  "arguments": {
    "path": ".",
    "show_untested": true
  }
}

Example for static analysis:
{
  "tool_name": "run_static_analysis",
  "arguments": {
    "path": "."
  }
}

Now, generate the tool call to complete the analysis request.
"""

class AnalysisAgent(BaseAgent):
    """
    A sub-agent that specializes in code analysis and review.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes an analysis task by calling an LLM to generate a tool call.
        """
        print(f"AnalysisAgent executing task: {task.description}")

        # Get all available tools, focusing on analysis tools
        all_tools = get_available_tools()
        analysis_tool_names = [
            'scan_security_issues', 'analyze_test_coverage', 'analyze_semantic_diff',
            'analyze_code_context', 'run_static_analysis', 'check_structural_consistency',
            'read_file', 'analyze_code_structures'
        ]
        available_tools = [tool for tool in all_tools if tool['function']['name'] in analysis_tool_names]

        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_reason = "LLM did not produce a valid tool call structure."
                context.add_error(f"AnalysisAgent: {error_reason}")
                self.request_replan(context, "Invalid LLM response for tool call", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_calls = response["message"]["tool_calls"]
            if not tool_calls:
                error_reason = "LLM response did not contain any tool calls."
                context.add_error(f"AnalysisAgent: {error_reason}")
                self.request_replan(context, "LLM produced no tool calls", detailed_reason=error_reason)
                raise ValueError(error_reason)

            tool_call = tool_calls[0]
            tool_name = tool_call['function']['name']
            arguments_str = tool_call['function']['arguments']

            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                error_msg = f"AnalysisAgent: LLM returned invalid JSON for arguments: {arguments_str}"
                context.add_error(error_msg)
                self.request_replan(context, "Invalid JSON arguments from LLM", detailed_reason=error_msg)
                return error_msg

            print(f"  → AnalysisAgent will call tool '{tool_name}' with arguments: {arguments}")

            result = execute_tool(tool_name, arguments)

            # Store analysis findings in context
            context.add_insight("analysis_agent", f"task_{task.task_id}_analysis", {
                "tool": tool_name,
                "summary": result[:500] if isinstance(result, str) else str(result)[:500]
            })

            return result

        except Exception as e:
            error_msg = f"Error executing task in AnalysisAgent: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Exception during tool execution", detailed_reason=error_msg)
            return error_msg
