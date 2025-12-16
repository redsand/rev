import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.execution.safety import is_scary_operation, prompt_scary_operation
from difflib import unified_diff
from typing import Tuple

CODE_WRITER_SYSTEM_PROMPT = """You are a specialized Code Writer agent. Your sole purpose is to execute a single coding task by calling the appropriate tool (`write_file` or `replace_in_file`).

You will be given a task description and context about the repository. Analyze them carefully.

CRITICAL RULES:
1.  You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2.  Based on the task, decide whether to create a new file (`write_file`) or modify an existing one (`replace_in_file`).
3.  If using `replace_in_file`, you MUST provide the *exact* `old_string` content to be replaced, including all original indentation and surrounding lines for context. Use the provided file content to construct this.
4.  Ensure the `new_string` is complete and correctly indented to match the surrounding code.
5.  If creating a new file, ensure the full file content is provided to the `write_file` tool.
6.  Your response MUST be a single, valid JSON object representing the tool call.

Example for `replace_in_file`:
{
  "tool_name": "replace_in_file",
  "arguments": {
    "file_path": "path/to/file.py",
    "old_string": "...\nline to be replaced\n...",
    "new_string": "...\nnew line of code\n..."
  }
}

Example for `write_file`:
{
  "tool_name": "write_file",
  "arguments": {
    "file_path": "path/to/new_file.py",
    "content": "full content of the new file"
  }
}

Now, generate the tool call to complete the user's request.
"""

class CodeWriterAgent(BaseAgent):
    """
    A sub-agent that specializes in writing and editing code.
    Implements intelligent error recovery with retry limits and user approval for changes.
    """

    # ANSI color codes for diff display (matching linear mode)
    _COLOR_RED = "\033[31m"      # Deletions
    _COLOR_GREEN = "\033[32m"    # Additions
    _COLOR_CYAN = "\033[36m"     # Headers
    _COLOR_RESET = "\033[0m"

    def _color_diff_line(self, line: str) -> str:
        """Apply color coding to diff lines (matching linear mode formatting)."""
        if line.startswith("+++") or line.startswith("---"):
            return f"{self._COLOR_CYAN}{line}{self._COLOR_RESET}"
        if line.startswith("@@"):
            return f"{self._COLOR_CYAN}{line}{self._COLOR_RESET}"
        if line.startswith("+"):
            return f"{self._COLOR_GREEN}{line}{self._COLOR_RESET}"
        if line.startswith("-"):
            return f"{self._COLOR_RED}{line}{self._COLOR_RESET}"
        return line

    def _generate_diff(self, old_content: str, new_content: str, file_path: str) -> str:
        """Generate a unified diff between old and new content."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff_lines = list(unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm=""
        ))

        if not diff_lines:
            return "(No changes)"

        # Color each line and join
        colored_diff = "\n".join(self._color_diff_line(line) for line in diff_lines)
        return colored_diff

    def _display_change_preview(self, tool_name: str, arguments: dict) -> None:
        """Display a preview of the changes to be made."""
        print(f"\n{'='*70}")
        print("📝 CODE CHANGE PREVIEW")
        print(f"{'='*70}")

        if tool_name == "replace_in_file":
            file_path = arguments.get("file_path", "unknown")
            old_string = arguments.get("old_string", "")
            new_string = arguments.get("new_string", "")

            print(f"\nFile: {file_path}")
            print(f"\n{self._COLOR_CYAN}--- Original Content{self._COLOR_RESET}")
            print(f"{self._COLOR_CYAN}+++ New Content{self._COLOR_RESET}\n")

            # Generate and display colored diff
            diff = self._generate_diff(old_string, new_string, file_path)
            print(diff)

            # Statistics
            old_lines = len(old_string.splitlines())
            new_lines = len(new_string.splitlines())
            print(f"\n{self._COLOR_CYAN}Changes:{self._COLOR_RESET} {old_lines} → {new_lines} lines")

        elif tool_name == "write_file":
            file_path = arguments.get("file_path", "unknown")
            content = arguments.get("content", "")
            lines = len(content.splitlines())

            print(f"\nFile: {file_path}")
            print(f"Action: {self._COLOR_GREEN}CREATE{self._COLOR_RESET}")
            print(f"Size: {lines} lines, {len(content)} bytes")

            # Show preview of first 20 lines
            preview_lines = content.splitlines()[:20]
            print(f"\n{self._COLOR_CYAN}Preview (first {min(20, len(preview_lines))} lines):{self._COLOR_RESET}")
            for i, line in enumerate(preview_lines, 1):
                print(f"  {i:3d}  {line[:66]}")  # Limit line width
            if len(content.splitlines()) > 20:
                print(f"  ... ({len(content.splitlines()) - 20} more lines)")

        print(f"\n{'='*70}")

    def _prompt_for_approval(self, tool_name: str, file_path: str) -> bool:
        """Prompt user to approve the change (matching linear mode behavior)."""
        # Check if this is a scary operation
        is_scary, scary_reason = is_scary_operation(tool_name, {"file_path": file_path})

        # For all file modifications, ask for approval
        operation_desc = f"{tool_name}: {file_path}"

        if is_scary:
            return prompt_scary_operation(operation_desc, scary_reason)
        else:
            # For non-scary operations, still ask for confirmation
            print(f"\n{'='*70}")
            print("👤 APPROVAL REQUIRED")
            print(f"{'='*70}")
            print(f"Operation: {operation_desc}")
            print(f"{'='*70}")

            try:
                while True:
                    response = input("Apply this change? [y/N]: ").strip().lower()

                    if response in {"y", "yes"}:
                        print("✓ Change approved, applying...")
                        return True
                    if response in {"n", "no", ""}:
                        print("✗ Change cancelled by user")
                        return False

                    print("Please respond with 'y' or 'n'.")
            except (KeyboardInterrupt, EOFError):
                print("\n[Cancelled by user]")
                return False

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a code writing or editing task by calling an LLM to generate a tool call.
        Implements error recovery with intelligent retry logic.
        """
        print(f"CodeWriterAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        available_tools = [tool for tool in get_available_tools() if tool['function']['name'] in ['write_file', 'replace_in_file']]

        messages = [
            {"role": "system", "content": CODE_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nRepository Context:\n{context.repo_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=available_tools)
            error_type = None
            error_detail = None

            # Debug: Print what we got back
            if not response:
                error_type = "empty_response"
                error_detail = "LLM returned None/empty response"
            elif "message" not in response:
                error_type = "missing_message_key"
                error_detail = f"Response missing 'message' key: {list(response.keys())}"
            elif "tool_calls" not in response["message"]:
                # Check if there's regular content instead
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
                    # Success - process tool call
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
                        print(f"  → CodeWriterAgent will call tool '{tool_name}'")

                        # Display change preview for write and replace operations
                        if tool_name in ["write_file", "replace_in_file"]:
                            self._display_change_preview(tool_name, arguments)

                            # Ask for user approval
                            file_path = arguments.get("file_path", "unknown")
                            if not self._prompt_for_approval(tool_name, file_path):
                                print(f"  ✗ Change rejected by user")
                                return "[USER_REJECTED] Change was not approved by user"

                        # Execute the tool
                        print(f"  ⏳ Applying {tool_name} to {arguments.get('file_path', 'file')}...")
                        result = execute_tool(tool_name, arguments)
                        print(f"  ✓ Successfully applied {tool_name}")
                        return result

            # If we reach here, there was an error
            if error_type:
                print(f"  ⚠️ CodeWriterAgent: {error_detail}")

                # Check if we should attempt recovery
                if self.should_attempt_recovery(task, context):
                    print(f"  → Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide clearer task instructions."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"CodeWriterAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in CodeWriterAgent: {e}"
            print(f"  ⚠️ {error_msg}")

            # Request recovery for exceptions
            if self.should_attempt_recovery(task, context):
                print(f"  → Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during code writing",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  → Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)