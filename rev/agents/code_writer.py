import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.execution.safety import is_scary_operation, prompt_scary_operation
from difflib import unified_diff
from typing import Tuple
import re
from pathlib import Path

from rev.core.tool_call_recovery import recover_tool_call_from_text
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev.tools.registry import execute_tool as execute_registry_tool


def _extract_target_files_from_description(description: str) -> list[str]:
    """Extract file paths mentioned in a task description.

    Returns a list of potential file paths found in the description.
    """
    if not description:
        return []

    paths = []

    # Match backticked paths like `src/module/__init__.py`
    backtick_pattern = r'`([^`]+\.(py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1))`'
    for match in re.finditer(backtick_pattern, description, re.IGNORECASE):
        paths.append(match.group(1))

    # Match quoted paths like "src/module/__init__.py"
    quote_pattern = r'"([^"]+\.(py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1))"'
    for match in re.finditer(quote_pattern, description, re.IGNORECASE):
        if match.group(1) not in paths:
            paths.append(match.group(1))

    # Match bare paths like src/module/__init__.py or main.py
    bare_pattern = r'\b([\w./\\-]+\.(py|js|ts|json|yaml|yml|md|txt|toml|cfg|ini|c|cpp|h|hpp|rs|go|rb|php|java|cs|sql|sh|bat|ps1))\b'
    for match in re.finditer(bare_pattern, description, re.IGNORECASE):
        candidate = match.group(1)
        # Filter out common false positives
        # We allow root files (no slash) if they have a recognized extension, 
        # but avoid simple things like ".py" or just "a.py" unless it's likely a real path
        if candidate not in paths and not candidate.startswith('.'):
            # Include if it has a slash OR if it's a multi-character name with extension
            if '/' in candidate or '\\' in candidate or len(candidate.split('.')[0]) > 1:
                paths.append(candidate)

    return paths


def _read_file_content_for_edit(file_path: str, max_lines: int = 500) -> str | None:
    """Read file content to include in edit context.

    Returns the file content or None if the file cannot be read.
    """
    try:
        result = execute_registry_tool("read_file", {"path": file_path})
        if isinstance(result, str):
            # Check for error in result
            try:
                result_json = json.loads(result)
                if isinstance(result_json, dict) and "error" in result_json:
                    return None
                # Return the content from the read_file result
                if isinstance(result_json, dict) and "content" in result_json:
                    content = result_json["content"]
                    # Limit to max_lines
                    lines = content.split('\n')
                    if len(lines) > max_lines:
                        return '\n'.join(lines[:max_lines]) + f"\n... (truncated, {len(lines) - max_lines} more lines)"
                    return content
            except json.JSONDecodeError:
                # Result is plain text content
                lines = result.split('\n')
                if len(lines) > max_lines:
                    return '\n'.join(lines[:max_lines]) + f"\n... (truncated, {len(lines) - max_lines} more lines)"
                return result
    except Exception:
        pass
    return None

CODE_WRITER_SYSTEM_PROMPT = """You are a specialized Code Writer agent. Your sole purpose is to execute a single coding task by calling the ONLY available tool for this specific task.

You will be given a task description, action_type, and repository context. Analyze them carefully.

SYSTEM CONTEXT:
- Use the provided 'System Information' (OS, Platform, Shell Type) to choose correct path syntax and commands.
- For complex validation or reproduction, you are encouraged to CREATE scripts (.ps1 for Windows, .sh for POSIX) using `write_file`.

TEST-DRIVEN DEVELOPMENT (TDD) AWARENESS:
- If implementing new functionality, tests should already exist (created in prior tasks)
- Your implementation should make existing tests pass, not create new features without tests
- Reference the test file in your implementation to ensure you're satisfying test requirements
- If you're writing a test file, be specific about expected behavior before implementation exists

CRITICAL RULES FOR IMPLEMENTATION QUALITY:
1.  You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2.  Use ONLY the tool(s) provided for this task's action_type. Other tools are NOT available:
    - For action_type="create_directory": ONLY use `create_directory`
    - For action_type="add": ONLY use `write_file`
    - For action_type="edit": use `rewrite_python_imports` (preferred for Python import rewrites) OR `replace_in_file`
    - For action_type="refactor": use `write_file`, `rewrite_python_imports`, or `replace_in_file` as needed
3.  If using `replace_in_file`, you MUST provide the *exact* `old_string` content to be replaced, including all original indentation and surrounding lines for context. Use the provided file content to construct this.
4.  Ensure the `new_string` is complete and correctly indented to match the surrounding code.
5.  If creating a new file, ensure the COMPLETE, FULL file content is provided to the `write_file` tool - not stubs or placeholders.
6.  Your response MUST be a single, valid JSON object representing the tool call.

CRITICAL RULES FOR CODE EXTRACTION:
7.  When extracting code from other files or refactoring:
    - DO extract the COMPLETE implementation, not stubs with "pass" statements
    - DO include ALL methods, properties, and logic from the source
    - DO NOT create placeholder implementations or TODO comments
    - DO preserve all original logic, error handling, and edge cases
    - If extracting from another file, read and understand the ENTIRE class/function before copying

8.  When the task mentions extracting or porting code:
    - Look for existing implementations in the repository that you can reference
    - If similar code exists, study it to understand patterns and style
    - Use those patterns when implementing new features
    - Document how the new code follows or differs from existing patterns

9.  Quality standards for implementation:
    - No stubs, placeholders, or TODO comments in new implementations
    - Full methods with complete logic (not "def method(): pass")
    - All imports and dependencies included
    - Proper error handling and validation
    - Docstrings explaining non-obvious logic

SECURITY-MINDED CODING (CRITICAL):
- Never store passwords, secrets, or API keys as plain strings in code.
- Use environment variables or secure configuration managers for sensitive data.
- Ensure proper input validation and sanitization.
- Avoid insecure practices like `eval()`, `exec()`, or unsanitized shell command execution.
- If creating a "password" field, it should be treated as sensitive (e.g., hashed/salted if for storage, or masked/secure-typed if for UI).

DEPENDENCY MANAGEMENT:
- If you modify `package.json`, `requirements.txt`, or other manifest files, ensure the plan includes an installation step. If it doesn't, mention it in your task completion summary.

IMPORT STRATEGY (CRITICAL):
- If you have just split a module into a package (a directory with `__init__.py` exporting symbols), STOP and THINK.
- Existing imports like `import package` or `from package import Symbol` are often STILL VALID because the `__init__.py` exports them.
- Do NOT replace a single valid import with dozens of individual module imports (e.g., `from package.module1 import ...`, `from package.module2 import ...`). This causes massive churn and linter errors.
- ONLY update an import if it is actually broken (e.g., `ModuleNotFoundError`).
- Prefer package-level imports: `from package import Symbol` is better than `from package.module import Symbol`.
- Never use `from module import *` in new code.

AST-AWARE EDITS (IMPORTANT):
- For Python import path migrations, prefer `rewrite_python_imports` over brittle string replacement.
- If preserving multiline import formatting/comments/parentheses is important, set `"engine": "libcst"`.
- For safer Python refactors, prefer these libcst tools over raw string edits:
  - `rewrite_python_keyword_args` (rename kw args at call sites)
  - `rename_imported_symbols` (rename imported symbols + update references in-file)
  - `move_imported_symbols` (move `from ... import ...` symbols between modules)
  - `rewrite_python_function_parameters` (rename/add/remove params + update calls; conservative)
- Use `replace_in_file` only when you cannot express the change as import rewrite rules (or when editing non-import code).

Example for `replace_in_file`:
{
  "tool_name": "replace_in_file",
  "arguments": {
    "path": "path/to/file.py",
    "find": "...\nline to be replaced\n...",
    "replace": "...\nnew line of code\n..."
  }
}

Example for `rewrite_python_imports`:
{
  "tool_name": "rewrite_python_imports",
  "arguments": {
    "path": "path/to/file.py",
    "rules": [
      {"from_module": "old.module", "to_module": "new.module", "match": "exact"}
    ]
  }
}

Example for `write_file`:
{
  "tool_name": "write_file",
  "arguments": {
    "path": "path/to/new_file.py",
    "content": "full content of the new file"
  }
}

Example for `create_directory`:
{
  "tool_name": "create_directory",
  "arguments": {
    "path": "path/to/new/directory"
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

    def _validate_import_targets(self, file_path: str, content: str) -> Tuple[bool, str]:
        """Validate that import statements target files that actually exist.

        Args:
            file_path: Path to the file being written
            content: Content being written to the file

        Returns:
            Tuple of (is_valid, warning_message)
        """
        # Only validate .py files
        if not file_path.endswith('.py'):
            return True, ""

        # Find import statements with relative or absolute paths
        # Pattern: from .module_name import ClassName or from module_name import ClassName
        import_pattern = r'from\s+(\.[a-zA-Z0-9._]+|[a-zA-Z0-9._]+)\s+import'
        matches = re.finditer(import_pattern, content)

        warnings = []
        # Resolve import targets relative to the file being written (not CWD).
        # This avoids false warnings like checking `<repo>/module.py` for imports
        # inside `<package>/__init__.py`.
        try:
            base_dir = (Path.cwd() / Path(file_path)).resolve(strict=False).parent
        except Exception:
            base_dir = Path.cwd()

        for match in matches:
            import_path = match.group(1)

            # Skip imports that don't start with . (they might be standard library or external packages)
            if not import_path.startswith('.'):
                continue

            # Convert relative import to file path
            # .module_name.submodule -> module_name/submodule.py
            # .module_name -> module_name.py or module_name/__init__.py
            module_parts = import_path.lstrip('.').replace('.', '/')

            # Check if file exists
            file_candidates = [
                base_dir / f"{module_parts}.py",
                base_dir / f"{module_parts}/__init__.py",
            ]

            file_exists = any(f.exists() for f in file_candidates)

            if not file_exists:
                warnings.append(f"Import target '{import_path}' does not exist (checked: {module_parts}.py or {module_parts}/__init__.py)")

        if warnings:
            return False, "; ".join(warnings)

        return True, ""

    def _tool_result_has_error(self, raw_result: str) -> Tuple[bool, str]:
        """Detect JSON tool failures (file tools typically return {"error": "..."})."""
        if not isinstance(raw_result, str):
            return False, ""
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError:
            return False, ""
        if isinstance(payload, dict) and isinstance(payload.get("error"), str) and payload["error"].strip():
            return True, payload["error"].strip()
        return False, ""

    def _tool_result_is_noop(self, tool_name: str, raw_result: str) -> Tuple[bool, str]:
        """Detect tool results that technically succeeded but made no changes."""
        tool = (tool_name or "").lower()
        if not isinstance(raw_result, str):
            return False, ""
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError:
            return False, ""
        if not isinstance(payload, dict):
            return False, ""

        if tool == "replace_in_file":
            replaced = payload.get("replaced")
            if isinstance(replaced, int) and replaced == 0:
                return True, (
                    "replace_in_file made no changes (replaced=0); likely `find` did not match the file. "
                    "RECOVERY: Ensure you're not escaping content incorrectly and check whitespace, indentation, and context. "
                    "Use read_file tool to verify the actual file content before retrying."
                )
        if tool == "rewrite_python_imports":
            changed = payload.get("changed")
            if isinstance(changed, int) and changed == 0:
                return True, "rewrite_python_imports made no changes (changed=0); likely no matching imports were found"
        if tool in {
            "rewrite_python_keyword_args",
            "rename_imported_symbols",
            "move_imported_symbols",
            "rewrite_python_function_parameters",
        }:
            changed = payload.get("changed")
            if isinstance(changed, int) and changed == 0:
                return True, f"{tool} made no changes (changed=0)"

        return False, ""

    def _validate_tool_args(self, tool_name: str, arguments: dict) -> Tuple[bool, str]:
        """Validate minimum required tool args to avoid tool-layer KeyErrors."""
        tool = (tool_name or "").lower()
        if not isinstance(arguments, dict):
            return False, "Tool arguments are not a JSON object"

        def _has_str(key: str) -> bool:
            return isinstance(arguments.get(key), str) and arguments.get(key).strip() != ""

        def _has_str_or_empty(key: str) -> bool:
            """Check if key exists and is a string (can be empty)."""
            return isinstance(arguments.get(key), str)

        if tool == "replace_in_file":
            # Special handling: 'replace' can be empty string (for deletions), but must exist
            if not _has_str("path") or not _has_str("find"):
                missing = [k for k in ("path", "find") if not _has_str(k)]
                return False, (
                    f"replace_in_file missing required keys: {', '.join(missing)}. "
                    "RECOVERY: Include all three required parameters: "
                    '{"path": "file/path.py", "find": "text to find", "replace": "replacement text (or empty string to delete)"}'
                )
            if not _has_str_or_empty("replace"):
                return False, (
                    "replace_in_file missing required key: replace. "
                    "RECOVERY: You MUST include the 'replace' parameter even if deleting content. "
                    'To delete text, use: {"path": "...", "find": "...", "replace": ""}. '
                    "Empty string is allowed for deletions."
                )
        elif tool == "rewrite_python_imports":
            if not _has_str("path"):
                return False, "rewrite_python_imports missing required key: path"
            rules = arguments.get("rules")
            if not isinstance(rules, list) or not rules:
                return False, "rewrite_python_imports missing required key: rules (non-empty list)"
        elif tool == "rewrite_python_keyword_args":
            missing = [k for k in ("path", "callee") if not _has_str(k)]
            if missing:
                return False, f"rewrite_python_keyword_args missing required keys: {', '.join(missing)}"
            renames = arguments.get("renames")
            if not isinstance(renames, list) or not renames:
                return False, "rewrite_python_keyword_args missing required key: renames (non-empty list)"
        elif tool == "rename_imported_symbols":
            if not _has_str("path"):
                return False, "rename_imported_symbols missing required key: path"
            renames = arguments.get("renames")
            if not isinstance(renames, list) or not renames:
                return False, "rename_imported_symbols missing required key: renames (non-empty list)"
        elif tool == "move_imported_symbols":
            missing = [k for k in ("path", "old_module", "new_module") if not _has_str(k)]
            if missing:
                return False, f"move_imported_symbols missing required keys: {', '.join(missing)}"
            symbols = arguments.get("symbols")
            if not isinstance(symbols, list) or not symbols:
                return False, "move_imported_symbols missing required key: symbols (non-empty list)"
        elif tool == "rewrite_python_function_parameters":
            missing = [k for k in ("path", "function") if not _has_str(k)]
            if missing:
                return False, f"rewrite_python_function_parameters missing required keys: {', '.join(missing)}"
        elif tool == "write_file":
            missing = [k for k in ("path", "content") if not _has_str(k)]
            if missing:
                return False, f"write_file missing required keys: {', '.join(missing)}"
        elif tool == "create_directory":
            if not _has_str("path"):
                return False, "create_directory missing required key: path"
        return True, ""

    def _should_retry_invalid_tool_args(self, context: RevContext, tool_name: str) -> bool:
        """Allow a few extra replans for invalid tool args (separate from global recovery)."""
        max_attempts = 3
        key = f"invalid_tool_args_attempts:{(tool_name or '').lower()}"
        attempts = context.get_agent_state(key, 0)
        if not isinstance(attempts, int):
            attempts = 0
        if attempts >= max_attempts:
            return False
        context.set_agent_state(key, attempts + 1)
        return True

    def _invalid_args_guidance(self, tool_name: str, arg_msg: str) -> str:
        tool = (tool_name or "").lower()
        if tool == "replace_in_file":
            return (
                f"{tool_name}: {arg_msg}. "
                "You must include either `find`/`replace` or `old_string`/`new_string`. "
                "`find`/`old_string` must be an exact substring from the current file content "
                "(include surrounding lines for context to ensure a unique match)."
            )
        return f"{tool_name}: {arg_msg}"

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
            file_path = arguments.get("path", "unknown")
            old_string = arguments.get("find", "")
            new_string = arguments.get("replace", "")

            print(f"\nFile: {file_path}")
            print(f"\n{self._COLOR_CYAN}--- Original Content{self._COLOR_RESET}")
            print(f"{self._COLOR_CYAN}+++ New Content{self._COLOR_RESET}\n")

            # Generate and display colored diff
            diff = self._generate_diff(old_string, new_string, file_path)
            print(diff)

            # Statistics
            old_lines = len(old_string.splitlines())
            new_lines = len(new_string.splitlines())
            print(f"\n{self._COLOR_CYAN}Changes:{self._COLOR_RESET} {old_lines} -> {new_lines} lines")

        elif tool_name == "rewrite_python_imports":
            file_path = arguments.get("path", "unknown")
            rules = arguments.get("rules", [])
            dry_run = bool(arguments.get("dry_run", False))

            print(f"\nFile: {file_path}")
            print(f"Action: {self._COLOR_GREEN}REWRITE IMPORTS{self._COLOR_RESET}")
            if dry_run:
                print(f"{self._COLOR_CYAN}Mode:{self._COLOR_RESET} dry_run=True (no file write)")

            print(f"\n{self._COLOR_CYAN}Rules:{self._COLOR_RESET}")
            try:
                print(json.dumps(rules, indent=2)[:4000])
            except Exception:
                print(str(rules)[:4000])

        elif tool_name == "write_file":
            file_path = arguments.get("path", "unknown")
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

        elif tool_name == "create_directory":
            dir_path = arguments.get("path", "unknown")
            print(f"\nDirectory: {dir_path}")
            print(f"Action: {self._COLOR_GREEN}CREATE DIRECTORY{self._COLOR_RESET}")

        elif tool_name == "move_file":
            src = arguments.get("src", "unknown")
            dest = arguments.get("dest", "unknown")
            print(f"\nSource: {src}")
            print(f"Destination: {dest}")
            print(f"Action: {self._COLOR_GREEN}MOVE/RENAME{self._COLOR_RESET}")

        elif tool_name == "copy_file":
            src = arguments.get("src", "unknown")
            dest = arguments.get("dest", "unknown")
            print(f"\nSource: {src}")
            print(f"Destination: {dest}")
            print(f"Action: {self._COLOR_GREEN}COPY{self._COLOR_RESET}")

        print(f"\n{'='*70}")

    def _prompt_for_approval(self, tool_name: str, file_path: str, context: 'RevContext' = None) -> bool:
        """Prompt user to approve the change (matching linear mode behavior)."""
        # If auto_approve is set in context, skip user prompts
        if context and context.auto_approve:
            return True

        # Check if this is a scary operation
        is_scary, scary_reason = is_scary_operation(tool_name, {"file_path": file_path})

        # For all file modifications, ask for approval
        operation_desc = f"{tool_name}: {file_path}"

        if is_scary:
            # If context is provided and auto_approve is set, pass it to the scary operation prompt
            auto_approve_scary = context.auto_approve if context else False
            return prompt_scary_operation(operation_desc, scary_reason, auto_approve=auto_approve_scary)
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

        # Constrain available tools based on task action_type
        all_tools = get_available_tools()

        # Determine which tools are appropriate for this action_type
        if task.action_type == "create_directory":
            # Directory creation tasks only get create_directory tool
            tool_names = ['create_directory']
        elif task.action_type == "add":
            # File creation tasks only get write_file tool
            tool_names = ['write_file']
        elif task.action_type == "edit":
            # File modification tasks may use AST-aware edits for safer Python refactors
            tool_names = [
                'rewrite_python_imports',
                'rewrite_python_keyword_args',
                'rename_imported_symbols',
                'move_imported_symbols',
                'rewrite_python_function_parameters',
                'replace_in_file',
                'apply_patch',
                'write_file',
                'copy_file',
                'move_file',
            ]
        elif task.action_type == "refactor":
            # Refactoring may need to create or modify files
            tool_names = [
                'write_file',
                'apply_patch',
                'rewrite_python_imports',
                'rewrite_python_keyword_args',
                'rename_imported_symbols',
                'move_imported_symbols',
                'rewrite_python_function_parameters',
                'replace_in_file',
                'copy_file',
                'move_file',
            ]
        else:
            # Unknown action types get all tools (fallback)
            tool_names = ['write_file', 'replace_in_file', 'create_directory', 'copy_file', 'move_file']

        available_tools = [tool for tool in all_tools if tool['function']['name'] in tool_names]
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=tool_names,
            max_tools=min(7, len(tool_names) if tool_names else 7),
        )
        available_tools = selected_tools

        # Build enhanced user message with extraction guidance
        task_guidance = f"Task (action_type: {task.action_type}): {task.description}"

        # Add extraction guidance based on task type
        if any(word in task.description.lower() for word in ["extract", "port", "move", "refactor", "create"]):
            task_guidance += """\n\nEXTRACTION GUIDANCE:
- Look for existing similar implementations in the codebase to understand patterns
- Extract COMPLETE implementations, not stubs or placeholders
- Include ALL methods, properties, and business logic from the source
- Preserve error handling and edge cases
- Do NOT use "pass" statements or TODO comments in new code
- Document any assumptions or changes from original implementation"""

        # For edit/refactor tasks, read target files and include their content
        # This ensures the LLM has the exact file content for replace_in_file
        file_content_section = ""
        if task.action_type in ("edit", "refactor"):
            target_files = _extract_target_files_from_description(task.description)
            if target_files:
                file_contents = []
                for file_path in target_files[:3]:  # Limit to 3 files to avoid context overflow
                    content = _read_file_content_for_edit(file_path)
                    if content:
                        file_contents.append(f"=== ACTUAL FILE CONTENT: {file_path} ===\n{content}\n=== END OF {file_path} ===")
                        print(f"  -> Including actual content of {file_path} for edit context")
                if file_contents:
                    file_content_section = "\n\nIMPORTANT - ACTUAL FILE CONTENT TO EDIT:\n" + "\n\n".join(file_contents)
                    file_content_section += "\n\nCRITICAL: When using replace_in_file, the 'find' parameter MUST be an EXACT substring from the ACTUAL FILE CONTENT above. Do NOT guess or fabricate the content."

        messages = [
            {"role": "system", "content": CODE_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": f"{task_guidance}\n\nSelected Context:\n{rendered_context}{file_content_section}"}
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
                        print(f"  -> CodeWriterAgent will call tool '{tool_name}'")

                        # Display change preview for file modifying operations
                        if tool_name in ["write_file", "replace_in_file", "create_directory", "move_file", "copy_file"]:
                            self._display_change_preview(tool_name, arguments)

                            # Validate import targets before proceeding
                            file_path = arguments.get("path") or arguments.get("dest") or "unknown"
                            if tool_name == "write_file":
                                content = arguments.get("content", "")
                                is_valid, warning_msg = self._validate_import_targets(file_path, content)
                                if not is_valid:
                                    print(f"\n  [WARN]  Import validation warning:")
                                    print(f"  {warning_msg}")
                                    print(f"  Note: This file has imports that may not exist. Proceed with caution.")

                            # Ask for user approval
                            if not self._prompt_for_approval(tool_name, file_path, context):
                                print(f"  ✗ Change rejected by user")
                                return "[USER_REJECTED] Change was not approved by user"

                        # Execute the tool
                        ok_args, arg_msg = self._validate_tool_args(tool_name, arguments)
                        if not ok_args:
                            print(f"  ✗ Invalid tool args: {arg_msg}")
                            if self._should_retry_invalid_tool_args(context, tool_name):
                                self.request_replan(
                                    context,
                                    reason="Missing required tool arguments",
                                    detailed_reason=self._invalid_args_guidance(tool_name, arg_msg),
                                )
                                return self.make_recovery_request("invalid_tool_args", arg_msg)
                            return self.make_failure_signal("invalid_tool_args", arg_msg)

                        print(f"  ⏳ Applying {tool_name} to {arguments.get('path', 'file')}...")
                        raw_result = execute_tool(tool_name, arguments, agent_name="code_writer")
                        has_error, error_msg = self._tool_result_has_error(raw_result)
                        if has_error:
                            print(f"  ✗ Tool reported error: {error_msg}")
                            if self.should_attempt_recovery(task, context):
                                self.request_replan(
                                    context,
                                    reason="Tool execution failed",
                                    detailed_reason=f"{tool_name} returned error: {error_msg}",
                                )
                                return self.make_recovery_request("tool_error", error_msg)
                            return self.make_failure_signal("tool_error", error_msg)

                        is_noop, noop_msg = self._tool_result_is_noop(tool_name, raw_result)
                        if is_noop:
                            print(f"  ? Tool made no changes: {noop_msg}")
                            if self.should_attempt_recovery(task, context):
                                if tool_name == "replace_in_file":
                                    # Track consecutive replace_in_file failures to escalate recovery suggestions
                                    consecutive_replace_failures = context.agent_state.get("consecutive_replace_failures", 0)
                                    consecutive_replace_failures += 1
                                    context.set_agent_state("consecutive_replace_failures", consecutive_replace_failures)

                                    # Escalate suggestions based on failure count
                                    if consecutive_replace_failures == 1:
                                        # First failure: suggest re-reading and trying again
                                        noop_msg = (
                                            f"{noop_msg}. RECOVERY STEP 1: Use read_file to verify the exact file content "
                                            f"(pay attention to whitespace and indentation), then retry with the correct find string."
                                        )
                                    elif consecutive_replace_failures == 2:
                                        # Second failure: suggest apply_patch
                                        noop_msg = (
                                            f"{noop_msg}. RECOVERY STEP 2: The find string still doesn't match. "
                                            f"Use apply_patch instead of replace_in_file, providing the exact original "
                                            f"content and full replacement. Or use write_file to completely replace the file."
                                        )
                                    else:
                                        # Third+ failure: suggest asking user or using different approach
                                        noop_msg = (
                                            f"{noop_msg}. RECOVERY STEP 3: Multiple edit attempts have failed. "
                                            f"Consider: (1) Use run_python_diagnostic to verify the issue still exists, "
                                            f"(2) Ask the user for clarification on what needs to change, or "
                                            f"(3) Use a completely different approach to solve the problem."
                                        )

                                self.request_replan(
                                    context,
                                    reason="Tool made no changes",
                                    detailed_reason=noop_msg,
                                )
                                return self.make_recovery_request("tool_noop", noop_msg)
                            return self.make_failure_signal("tool_noop", noop_msg)

                        # Successful tool execution - reset consecutive failure counters
                        if tool_name == "replace_in_file":
                            context.set_agent_state("consecutive_replace_failures", 0)

                        print(f"  ✓ Successfully applied {tool_name}")
                        return build_subagent_output(
                            agent_name="CodeWriterAgent",
                            tool_name=tool_name,
                            tool_args=arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

            # If we reach here, there was an error
            if error_type:
                if error_type in {"text_instead_of_tool_call", "empty_tool_calls", "missing_tool_calls"}:
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=[t["function"]["name"] for t in available_tools],
                    )
                    if recovered:
                        tool_name = recovered.name
                        arguments = recovered.arguments
                        print(f"  -> Recovered tool call from text output: {tool_name}")

                        if tool_name in ["write_file", "replace_in_file", "create_directory", "move_file", "copy_file"]:
                            self._display_change_preview(tool_name, arguments)

                            file_path = arguments.get("path") or arguments.get("dest") or "unknown"
                            if tool_name == "write_file":
                                content = arguments.get("content", "")
                                is_valid, warning_msg = self._validate_import_targets(file_path, content)
                                if not is_valid:
                                    print("\n  [WARN] Import validation warning:")
                                    print(f"  {warning_msg}")
                                    print("  Note: This file has imports that may not exist. Proceed with caution.")

                            if not self._prompt_for_approval(tool_name, file_path, context):
                                print("  [REJECTED] Change rejected by user")
                                return "[USER_REJECTED] Change was not approved by user"

                        ok_args, arg_msg = self._validate_tool_args(tool_name, arguments)
                        if not ok_args:
                            print(f"  Invalid tool args: {arg_msg}")
                            if self._should_retry_invalid_tool_args(context, tool_name):
                                self.request_replan(
                                    context,
                                    reason="Missing required tool arguments",
                                    detailed_reason=self._invalid_args_guidance(tool_name, arg_msg),
                                )
                                return self.make_recovery_request("invalid_tool_args", arg_msg)
                            return self.make_failure_signal("invalid_tool_args", arg_msg)

                        print(f"  Applying {tool_name} to {arguments.get('path', 'file')}...")
                        raw_result = execute_tool(tool_name, arguments, agent_name="code_writer")
                        has_error, error_msg = self._tool_result_has_error(raw_result)
                        if has_error:
                            print(f"  Tool reported error: {error_msg}")
                            if self.should_attempt_recovery(task, context):
                                self.request_replan(
                                    context,
                                    reason="Tool execution failed",
                                    detailed_reason=f"{tool_name} returned error: {error_msg}",
                                )
                                return self.make_recovery_request("tool_error", error_msg)
                            return self.make_failure_signal("tool_error", error_msg)

                        is_noop, noop_msg = self._tool_result_is_noop(tool_name, raw_result)
                        if is_noop:
                            print(f"  Tool made no changes: {noop_msg}")
                            if self.should_attempt_recovery(task, context):
                                if tool_name == "replace_in_file":
                                    # Track consecutive replace_in_file failures to escalate recovery suggestions
                                    consecutive_replace_failures = context.agent_state.get("consecutive_replace_failures", 0)
                                    consecutive_replace_failures += 1
                                    context.set_agent_state("consecutive_replace_failures", consecutive_replace_failures)

                                    # Escalate suggestions based on failure count
                                    if consecutive_replace_failures == 1:
                                        # First failure: suggest re-reading and trying again
                                        noop_msg = (
                                            f"{noop_msg}. RECOVERY STEP 1: Use read_file to verify the exact file content "
                                            f"(pay attention to whitespace and indentation), then retry with the correct find string."
                                        )
                                    elif consecutive_replace_failures == 2:
                                        # Second failure: suggest apply_patch
                                        noop_msg = (
                                            f"{noop_msg}. RECOVERY STEP 2: The find string still doesn't match. "
                                            f"Use apply_patch instead of replace_in_file, providing the exact original "
                                            f"content and full replacement. Or use write_file to completely replace the file."
                                        )
                                    else:
                                        # Third+ failure: suggest asking user or using different approach
                                        noop_msg = (
                                            f"{noop_msg}. RECOVERY STEP 3: Multiple edit attempts have failed. "
                                            f"Consider: (1) Use run_python_diagnostic to verify the issue still exists, "
                                            f"(2) Ask the user for clarification on what needs to change, or "
                                            f"(3) Use a completely different approach to solve the problem."
                                        )

                                self.request_replan(
                                    context,
                                    reason="Tool made no changes",
                                    detailed_reason=noop_msg,
                                )
                                return self.make_recovery_request("tool_noop", noop_msg)
                            return self.make_failure_signal("tool_noop", noop_msg)

                        # Successful tool execution - reset consecutive failure counters
                        if tool_name == "replace_in_file":
                            context.set_agent_state("consecutive_replace_failures", 0)

                        print(f"  Successfully applied {tool_name}")
                        return build_subagent_output(
                            agent_name="CodeWriterAgent",
                            tool_name=tool_name,
                            tool_args=arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

                print(f"  [WARN] CodeWriterAgent: {error_detail}")

                # Check if we should attempt recovery
                if self.should_attempt_recovery(task, context):
                    print(f"  -> Requesting replan (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                    self.request_replan(
                        context,
                        reason="Tool call generation failed",
                        detailed_reason=f"Error type: {error_type}. Details: {error_detail}. Please provide clearer task instructions."
                    )
                    return self.make_recovery_request(error_type, error_detail)
                else:
                    print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                    context.add_error(f"CodeWriterAgent: {error_detail} (after {recovery_attempts} recovery attempts)")
                    return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            error_msg = f"Exception in CodeWriterAgent: {e}"
            print(f"  [WARN] {error_msg}")

            # Request recovery for exceptions
            if self.should_attempt_recovery(task, context):
                print(f"  -> Requesting replan due to exception (attempt {recovery_attempts}/{self.MAX_RECOVERY_ATTEMPTS})...")
                self.request_replan(
                    context,
                    reason="Exception during code writing",
                    detailed_reason=str(e)
                )
                return self.make_recovery_request("exception", str(e))
            else:
                print(f"  -> Max recovery attempts ({self.MAX_RECOVERY_ATTEMPTS}) exhausted. Marking task as failed.")
                context.add_error(error_msg)
                return self.make_failure_signal("exception", error_msg)
