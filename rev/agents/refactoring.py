import json
import logging
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
import re

# Set up logging for RefactoringAgent
logger = logging.getLogger(__name__)

REFACTORING_SYSTEM_PROMPT = """You are a specialized Refactoring agent. Your purpose is to restructure code for improved readability, maintainability, and performance while preserving functionality.

IMPORTANT FOR EXTRACTION TASKS:
When asked to extract classes from a file into separate files:
1. Read the source file carefully to identify all classes
2. For each class, create a new file with:
   - The class definition
   - All necessary imports
   - Proper module structure
3. Create an __init__.py file that imports all extracted classes
4. Update the original file to import from the new files (or replace with imports)

You MUST use the write_file tool for each extracted file. Do not just read files - you must CREATE new files."""

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
        logger.info(f"[REFACTORING] Starting task: {task.description}")

        result = self._execute_simple_refactoring_task(task, context)

        logger.info(f"[REFACTORING] Task result: {result[:100] if isinstance(result, str) else result}")
        return result


    def _execute_simple_refactoring_task(self, task: Task, context: RevContext) -> str:
        """
        Handles simple, single-tool-call refactoring tasks.
        """
        recovery_attempts = self.increment_recovery_attempts(task, context)
        logger.debug(f"[REFACTORING] Recovery attempts: {recovery_attempts}")

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file', 'read_file']]
        logger.debug(f"[REFACTORING] Available tools: {[t['function']['name'] for t in available_tools]}")

        messages = [
            {"role": "system", "content": REFACTORING_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        logger.debug(f"[REFACTORING] Sending to LLM with {len(messages)} messages")

        try:
            response = ollama_chat(messages, tools=available_tools)
            logger.debug(f"[REFACTORING] LLM Response keys: {response.keys() if response else 'None'}")

            error_type, error_detail = None, None

            if not response or "message" not in response:
                error_type = "invalid_llm_response"
                error_detail = f"LLM response was empty or missing 'message' key. Response: {response}"
                logger.error(f"[REFACTORING] {error_type}: {error_detail}")
            elif "tool_calls" not in response["message"]:
                error_type = "no_tool_calls"
                error_detail = f"LLM response did not contain tool_calls. Message keys: {response['message'].keys() if response['message'] else 'None'}"
                logger.error(f"[REFACTORING] {error_type}: {error_detail}")
            else:
                tool_calls = response["message"]["tool_calls"]
                logger.info(f"[REFACTORING] LLM generated {len(tool_calls)} tool call(s)")

                if not tool_calls:
                    error_type = "empty_tool_calls"
                    error_detail = "LLM response contained empty tool_calls list"
                    logger.error(f"[REFACTORING] {error_type}: {error_detail}")
                else:
                    tool_call = tool_calls[0]
                    tool_name = tool_call['function']['name']
                    arguments_str = tool_call['function']['arguments']

                    logger.info(f"[REFACTORING] Tool call #1: {tool_name}")
                    logger.debug(f"[REFACTORING] Arguments: {arguments_str}")

                    try:
                        arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
                        logger.info(f"[REFACTORING] Executing tool '{tool_name}' with parsed arguments")
                        print(f"  → RefactoringAgent will call tool '{tool_name}'")
                        print(f"    Arguments: {json.dumps(arguments, indent=2)[:200]}...")

                        result = execute_tool(tool_name, arguments)
                        logger.info(f"[REFACTORING] Tool execution successful: {str(result)[:100]}")
                        return result
                    except json.JSONDecodeError as je:
                        error_type, error_detail = "invalid_json", f"Invalid JSON in tool arguments: {arguments_str[:200]}"
                        logger.error(f"[REFACTORING] {error_type}: {error_detail}")

            if error_type:
                print(f"  ⚠️ RefactoringAgent: {error_detail}")
                logger.warning(f"[REFACTORING] {error_type}: {error_detail}")

                if self.should_attempt_recovery(task, context):
                    logger.info(f"[REFACTORING] Attempting recovery (attempt {recovery_attempts})")
                    self.request_replan(context, reason="Tool call generation failed", detailed_reason=f"{error_type}: {error_detail}")
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    logger.error(f"[REFACTORING] Max recovery attempts reached, marking as final failure")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in RefactoringAgent: {e}"
            print(f"  ⚠️ {error_msg}")
            logger.exception(f"[REFACTORING] {error_msg}")

            if self.should_attempt_recovery(task, context):
                logger.info(f"[REFACTORING] Attempting recovery after exception (attempt {recovery_attempts})")
                self.request_replan(context, reason="Exception during refactoring", detailed_reason=str(e))
                return self.make_recovery_request("exception", str(e))
            else:
                logger.error(f"[REFACTORING] Max recovery attempts reached after exception")
                return self.make_failure_signal("exception", error_msg)

        error_msg = "An unhandled error occurred in the RefactoringAgent."
        logger.error(f"[REFACTORING] {error_msg}")
        return self.make_failure_signal("unhandled_error", error_msg)