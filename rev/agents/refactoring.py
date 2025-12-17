import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
import re

REFACTORING_SYSTEM_PROMPT = """You are a specialized Refactoring agent. Your purpose is to restructure code for improved readability, maintainability, and performance while preserving functionality."""

class RefactoringAgent(BaseAgent):
    """
    A sub-agent that specializes in code refactoring.
    This agent can handle complex refactoring tasks that require multiple steps,
    such as splitting a file into multiple new files.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a refactoring task by leveraging the LLM's general
        code understanding capabilities for a language-agnostic approach.
        """
        print(f"RefactoringAgent executing task: {task.description}")
        return self._execute_simple_refactoring_task(task, context)


    def _execute_simple_refactoring_task(self, task: Task, context: RevContext) -> str:
        """
        Handles simple, single-tool-call refactoring tasks.
        """
        recovery_attempts = self.increment_recovery_attempts(task, context)
        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file']]

        messages = [
            {"role": "system", "content": REFACTORING_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)
            error_type, error_detail = None, None

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                error_type = "invalid_llm_response"
                error_detail = "LLM response was empty or did not contain a tool call."
            else:
                tool_call = response["message"]["tool_calls"][0]
                tool_name = tool_call['function']['name']
                arguments_str = tool_call['function']['arguments']
                
                try:
                    arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
                    print(f"  → RefactoringAgent will call tool '{tool_name}' with arguments: {arguments}")
                    return execute_tool(tool_name, arguments)
                except json.JSONDecodeError:
                    error_type, error_detail = "invalid_json", f"Invalid JSON in tool arguments: {arguments_str[:200]}"
            
            if error_type:
                print(f"  ⚠️ RefactoringAgent: {error_detail}")
                if self.should_attempt_recovery(task, context):
                    self.request_replan(context, reason="Tool call generation failed", detailed_reason=f"{error_type}: {error_detail}")
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in RefactoringAgent: {e}"
            print(f"  ⚠️ {error_msg}")
            if self.should_attempt_recovery(task, context):
                self.request_replan(context, reason="Exception during refactoring", detailed_reason=str(e))
                return self.make_recovery_request("exception", str(e))
            else:
                return self.make_failure_signal("exception", error_msg)
        
        return self.make_failure_signal("unhandled_error", "An unhandled error occurred in the RefactoringAgent.")