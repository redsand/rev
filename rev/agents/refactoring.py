import json
import logging
import re
from pathlib import Path

from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev import config
from rev.execution.ultrathink_prompts import get_ultrathink_prompt

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
5. Prefer the `split_python_module_classes` tool to automate this process when working with large modules.

IMPORT STRATEGY (CRITICAL):
- If you have just split a module into a package (a directory with `__init__.py` exporting symbols), STOP and THINK.
- Existing imports like `import package` or `from package import Symbol` are often STILL VALID because the `__init__.py` exports them.
- Do NOT replace a single valid import with dozens of individual module imports (e.g., `from package.module1 import ...`, `from package.module2 import ...`). This causes massive churn and linter errors.
- ONLY update an import if it is actually broken (e.g., `ModuleNotFoundError`).
- Prefer package-level imports: `from package import Symbol` is better than `from package.module import Symbol`.
- Never use `from module import *` in new code.

AST-AWARE EDITS (IMPORTANT):
- When updating Python import paths (e.g., after splitting/moving modules), prefer the `rewrite_python_imports` tool over
  brittle string replacement.
- If preserving multiline import formatting/comments/parentheses is important, set `"engine": "libcst"`.

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
        logger.info(f"[REFACTORING] Starting task: {task.description}")

        # Check if an improved system prompt was provided (for adaptive retry)
        system_prompt = getattr(task, '_override_system_prompt', None) or REFACTORING_SYSTEM_PROMPT

        # Apply ultrathink mode if enabled (unless overridden by retry prompt)
        if not getattr(task, '_override_system_prompt', None) and config.ULTRATHINK_MODE == "on":
            system_prompt = get_ultrathink_prompt(REFACTORING_SYSTEM_PROMPT, 'refactoring')
            logger.info(f"[REFACTORING] 🧠 ULTRATHINK MODE ENABLED - Using enhanced reasoning prompt")
        elif system_prompt != REFACTORING_SYSTEM_PROMPT:
            logger.info(f"[REFACTORING] Using improved system prompt for retry")

        auto_result = self._attempt_structured_split(task, context)
        if auto_result is not None:
            return auto_result

        result = self._execute_simple_refactoring_task(task, context, system_prompt)

        logger.info(f"[REFACTORING] Task result: {result[:100] if isinstance(result, str) else result}")
        return result

    def _attempt_structured_split(self, task: Task, context: RevContext) -> str | None:
        """Automatically invoke the split tool when the task clearly requests it."""
        desc_lower = task.description.lower()
        split_keywords = (
            "break out",
            "split",
            "separate",
            "extract",
            "individual files",
            "its own file",
            "into its own file",
            "each class",
        )
        has_source = bool(re.search(r'([A-Za-z0-9_\-./]+\.py)', task.description))
        has_target_dir = bool(re.search(r'([A-Za-z0-9_\-./]+/)', task.description))
        if not any(keyword in desc_lower for keyword in split_keywords) and not (has_source and has_target_dir):
            return None

        def _clean_path(raw: str) -> str:
            cleaned = raw.strip().strip('"').strip("'").replace("\\", "/")
            cleaned = re.sub(r"/{2,}", "/", cleaned)
            return cleaned

        source_candidates = re.findall(r'([A-Za-z0-9_\-./]+\.py)', task.description)
        if not source_candidates:
            return None

        source_path = _clean_path(source_candidates[0])
        if not source_path:
            return None

        source_path_obj = Path(source_path)
        prefix = "./" if source_path.startswith("./") else ""
        default_target = prefix + source_path_obj.with_suffix("").as_posix()

        dir_candidates = re.findall(r'([A-Za-z0-9_\-./]+/)', task.description)
        target_dir = None
        source_stem = source_path_obj.stem.lower()
        for candidate in dir_candidates:
            cleaned = _clean_path(candidate).rstrip("/")
            if not cleaned:
                continue
            candidate_name = Path(cleaned).name.lower()
            if candidate_name == source_stem or source_stem in candidate_name:
                target_dir = cleaned
                break

        if not target_dir:
            target_dir = default_target

        print(f"  -> Using split_python_module_classes on {source_path} -> {target_dir}")
        arguments = {
            "source_path": source_path,
            "target_directory": target_dir,
            "overwrite": False,
        }
        result = execute_tool("split_python_module_classes", arguments)
        return build_subagent_output(
            agent_name="RefactoringAgent",
            tool_name="split_python_module_classes",
            tool_args=arguments,
            tool_output=result,
            context=context,
            task_id=task.task_id,
        )


    def _execute_simple_refactoring_task(self, task: Task, context: RevContext, system_prompt: str = None) -> str:
        """
        Handles simple, single-tool-call refactoring tasks.
        """
        recovery_attempts = self.increment_recovery_attempts(task, context)
        logger.debug(f"[REFACTORING] Recovery attempts: {recovery_attempts}")

        # Use provided system_prompt or fall back to default
        if system_prompt is None:
            system_prompt = REFACTORING_SYSTEM_PROMPT

        available_tools = [
            tool
            for tool in get_available_tools()
            if tool['function']['name'] in [
                'write_file',
                'replace_in_file',
                'rewrite_python_imports',
                'rewrite_python_keyword_args',
                'rename_imported_symbols',
                'move_imported_symbols',
                'rewrite_python_function_parameters',
                'read_file',
                'split_python_module_classes',
            ]
        ]
        logger.debug(f"[REFACTORING] Available tools: {[t['function']['name'] for t in available_tools]}")

        all_tools = get_available_tools()
        candidate_tool_names = [
            'write_file',
            'rewrite_python_imports',
            'rewrite_python_keyword_args',
            'rename_imported_symbols',
            'move_imported_symbols',
            'rewrite_python_function_parameters',
            'replace_in_file',
            'read_file',
            'split_python_module_classes',
        ]
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=candidate_tool_names,
            max_tools=4,
        )
        available_tools = selected_tools

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Task: {task.description}\n\nSelected Context:\n{rendered_context}"}
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
                        print(f"  -> RefactoringAgent will call tool '{tool_name}'")
                        print(f"    Arguments: {json.dumps(arguments, indent=2)[:200]}...")

                        result = execute_tool(tool_name, arguments)
                        logger.info(f"[REFACTORING] Tool execution successful: {str(result)[:100]}")
                        return build_subagent_output(
                            agent_name="RefactoringAgent",
                            tool_name=tool_name,
                            tool_args=arguments,
                            tool_output=result,
                            context=context,
                            task_id=task.task_id,
                        )
                    except json.JSONDecodeError as je:
                        error_type, error_detail = "invalid_json", f"Invalid JSON in tool arguments: {arguments_str[:200]}"
                        logger.error(f"[REFACTORING] {error_type}: {error_detail}")

            if error_type:
                recovered = None
                retried = False
                if response and isinstance(response.get("message"), dict):
                    recovered = recover_tool_call_from_text(
                        response["message"].get("content", ""),
                        allowed_tools=[t["function"]["name"] for t in available_tools],
                    )
                    if not recovered:
                        recovered = recover_tool_call_from_text_lenient(
                            response["message"].get("content", ""),
                            allowed_tools=[t["function"]["name"] for t in available_tools],
                        )
                        if recovered:
                            print("  [WARN] RefactoringAgent: using lenient tool call recovery from text output")
                if not recovered:
                    recovered = retry_tool_call_with_response_format(
                        messages,
                        available_tools,
                        allowed_tools=[t["function"]["name"] for t in available_tools],
                    )
                    if recovered:
                        retried = True
                        print(f"  -> Retried tool call with JSON format: {recovered.name}")
                if recovered:
                    if not recovered.name:
                        return self.make_failure_signal("missing_tool", "Recovered tool call missing name")
                    if not recovered.arguments:
                        return self.make_failure_signal("missing_tool_args", "Recovered tool call missing arguments")
                    if not retried:
                        print(f"  -> Recovered tool call from text output: {recovered.name}")
                    raw_result = execute_tool(recovered.name, recovered.arguments)
                    return build_subagent_output(
                        agent_name="RefactoringAgent",
                        tool_name=recovered.name,
                        tool_args=recovered.arguments,
                        tool_output=raw_result,
                        context=context,
                        task_id=task.task_id,
                    )

                print(f"  [WARN] RefactoringAgent: {error_detail}")
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
            print(f"  [WARN] {error_msg}")
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
