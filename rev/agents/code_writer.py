import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.execution.safety import is_scary_operation, prompt_scary_operation
from difflib import unified_diff
from typing import Any, Dict, List, Optional, Tuple
import re
from pathlib import Path

from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient, RecoveredToolCall
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev.tools.registry import execute_tool as execute_registry_tool
from rev import config
from rev.execution.ultrathink_prompts import ULTRATHINK_CODE_WRITER_PROMPT


def _extract_target_files_from_description(description: str) -> list[str]:
    """Extract file paths mentioned in a task description.

    Returns a list of potential file paths found in the description.

    SIMPLIFIED: Instead of hardcoding file extensions, accept any path-like string.
    This catches .prisma, .vue, .tsx, .jsx, .graphql, and any other file type.
    """
    if not description:
        return []

    paths = []

    # Match backticked paths like `src/module/file.ext` (any extension)
    backtick_pattern = r'`([^`]+\.\w+)`'
    for match in re.finditer(backtick_pattern, description, re.IGNORECASE):
        paths.append(match.group(1))

    # Match quoted paths like "src/module/file.ext" (any extension)
    quote_pattern = r'"([^"]+\.\w+)"'
    for match in re.finditer(quote_pattern, description, re.IGNORECASE):
        if match.group(1) not in paths:
            paths.append(match.group(1))

    # Match bare paths like src/module/file.ext or backend/prisma/schema.prisma
    # Pattern: word chars, slashes, dots, hyphens + dot + extension
    bare_pattern = r'\b([\w./\\-]+\.\w+)\b'
    allowed_bare = {
        "package.json",
        "tsconfig.json",
        "jsconfig.json",
        "vite.config.ts",
        "vitest.config.ts",
        "jest.config.js",
        "README.md",
        "readme.md",
    }
    verb_hint = re.compile(r"\b(edit|update|modify|create|add|remove|delete|replace|rename|refactor|fix|read|inspect|open|write)\b", re.IGNORECASE)
    for match in re.finditer(bare_pattern, description, re.IGNORECASE):
        candidate = match.group(1)
        if candidate in paths or candidate.startswith('.'):
            continue
        end_idx = match.end()
        if end_idx < len(description) and description[end_idx] == "(":
            # Avoid method-like tokens such as express.json()
            continue
        if '/' in candidate or '\\' in candidate:
            paths.append(candidate)
            continue
        if candidate.lower() in allowed_bare:
            paths.append(candidate)
            continue
        context_start = max(0, match.start() - 25)
        context = description[context_start:match.start()]
        if verb_hint.search(context):
            paths.append(candidate)

    return paths


def _read_file_content_for_edit(file_path: str, max_lines: int = 2000) -> str | None:
    """Read file content to include in edit context.

    Returns the file content or None if the file cannot be read.

    For files over max_lines, falls back to using write_file strategy instead of replace_in_file.
    """
    def _normalize_content(content: str) -> str:
        lines = content.split('\n')
        if len(lines) > max_lines:
            return (
                content +
                f"\n\nWARNING: This file has {len(lines)} lines (>{max_lines}). "
                "For large files, consider using write_file with the complete new content "
                "instead of replace_in_file, as it's more reliable for extensive changes."
            )
        return content

    def _try_read(path_value: str) -> Optional[str]:
        result = execute_registry_tool("read_file", {"path": path_value})
        if isinstance(result, str):
            try:
                result_json = json.loads(result)
                if isinstance(result_json, dict):
                    if "error" in result_json:
                        return None
                    if result_json.get("is_dir"):
                        return None
                    if "content" in result_json:
                        return _normalize_content(result_json["content"])
                    if any(key in result_json for key in ("path", "entries", "count", "hint")):
                        return None
                    # The file content itself may be valid JSON (e.g. package.json).
                    return _normalize_content(result)
            except json.JSONDecodeError:
                return _normalize_content(result)
        return None

    try:
        content = _try_read(file_path)
        if content:
            return content

        # Fallback: resolve relative path against workspace root when workdir is scoped.
        try:
            candidate = Path(file_path)
            if not candidate.is_absolute():
                root_path = Path(config.ROOT)
                alt = root_path / candidate
                content = _try_read(str(alt))
                if content:
                    return content
        except Exception:
            pass
    except Exception:
        pass
    return None


def _task_is_command_only(description: str) -> bool:
    if not description:
        return False
    desc = description.lower()
    return bool(
        re.search(
            r"\b(run_cmd|run_terminal_command|run_tests|execute command|install|npm install|npm ci|yarn install|"
            r"pnpm install|pip install|pipenv install|poetry install|pipx install|conda install|bundle install|composer install|"
            r"apt-get|apt install|brew install|choco install|winget install|yum install|dnf install|apk add|pacman -S|zypper install)\b",
            desc,
        )
    )

CODE_WRITER_SYSTEM_PROMPT = """You are a specialized Code Writer agent. Your sole purpose is to execute a single coding task by calling the ONLY available tool for this specific task.

⚠️ CRITICAL WARNING - TOOL EXECUTION IS MANDATORY ⚠️
YOU MUST CALL A TOOL. DO NOT RETURN EXPLANATORY TEXT. DO NOT DESCRIBE WHAT YOU WOULD DO.
IF YOU RETURN TEXT INSTEAD OF A TOOL CALL, THE TASK WILL FAIL PERMANENTLY.

Your response must be ONLY a JSON tool call. Example:
{
  "tool_name": "write_file",
  "arguments": {
    "path": "example.js",
    "content": "console.log('hello');"
  }
}

DO NOT wrap the JSON in markdown. DO NOT add any other text before or after the JSON.

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
3.  If using `replace_in_file`, follow these MANDATORY rules:
    a) The `find` parameter MUST be an EXACT substring from the provided file content - character-for-character identical
    b) Include 2-3 surrounding lines for context to ensure the match is unique
    c) COPY the exact text from the provided file content - DO NOT type it from memory or modify spacing
    d) Preserve ALL whitespace, tabs, and indentation exactly as shown
    e) If you cannot find the exact text in the provided content, use `write_file` instead to rewrite the whole file
    f) For small edits (1-20 lines), use replace_in_file; for large changes (>50 lines), use write_file
4.  Ensure the `replace` parameter is complete and correctly indented to match the surrounding code.
5.  If creating a new file, ensure the COMPLETE, FULL file content is provided to the `write_file` tool - not stubs or placeholders.
6.  Your response MUST be a single, valid JSON object representing the tool call. NEVER wrap JSON in markdown code fences (```json...```).

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

    def _retry_with_diff_or_file(
        self,
        messages: List[Dict[str, str]],
        *,
        allowed_tools: List[str],
    ) -> Optional[RecoveredToolCall]:
        """Fallback retry asking for unified diff or full file content."""
        guidance = (
            "Tool calling failed. Return ONLY one of the following:\n"
            "1) A unified diff (diff --git or ---/+++ with @@ hunks), OR\n"
            "2) A fenced file block with the first line 'path: <path>' and the full file content.\n"
            "Do NOT include commentary."
        )
        retry_messages = list(messages) + [{"role": "user", "content": guidance}]
        response = ollama_chat(retry_messages, tools=None, supports_tools=False)
        content = ""
        if isinstance(response, dict):
            message = response.get("message") or {}
            if isinstance(message, dict):
                content = message.get("content") or ""
        return recover_tool_call_from_text(content, allowed_tools=allowed_tools)

    def _retry_with_write_file(
        self,
        messages: List[Dict[str, str]],
        *,
        allowed_tools: List[str],
    ) -> Optional[RecoveredToolCall]:
        """Fallback retry forcing full file content output."""
        guidance = (
            "replace_in_file did not match. Return ONLY a fenced file block with:\n"
            "path: <path>\n"
            "<full file content>\n"
            "Do NOT return a diff or commentary."
        )
        retry_messages = list(messages) + [{"role": "user", "content": guidance}]
        response = ollama_chat(retry_messages, tools=None, supports_tools=False)
        content = ""
        if isinstance(response, dict):
            message = response.get("message") or {}
            if isinstance(message, dict):
                content = message.get("content") or ""
        recovered = recover_tool_call_from_text(content, allowed_tools=allowed_tools)
        if recovered and recovered.name == "write_file":
            return recovered
        return None

    def _retry_with_tool_call_repair(
        self,
        messages: List[Dict[str, str]],
        raw_content: str,
        *,
        allowed_tools: List[str],
        tools: List[Dict[str, Any]],
    ) -> Optional[RecoveredToolCall]:
        """Attempt to repair a tool call when the model returned JSON-like text."""
        if not raw_content:
            return None
        if not any(token in raw_content for token in ("tool_name", "\"arguments\"", "\"function\"")):
            return None
        guidance = (
            "Your previous response attempted a tool call but was invalid or truncated. "
            "Use it as a hint and return ONLY a valid JSON tool call object with "
            "\"tool_name\" and \"arguments\". No commentary."
        )
        repair_messages = list(messages) + [
            {"role": "assistant", "content": raw_content},
            {"role": "user", "content": guidance},
        ]
        return retry_tool_call_with_response_format(
            repair_messages,
            tools,
            allowed_tools=allowed_tools,
        )

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

        elif tool_name == "apply_patch":
            patch_content = arguments.get("patch", "")
            print(f"\nAction: {self._COLOR_GREEN}APPLY PATCH{self._COLOR_RESET}")
            print(f"\n{self._COLOR_CYAN}Patch Content:{self._COLOR_RESET}")
            for line in patch_content.splitlines():
                print(self._color_diff_line(line))

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
                # Color new content green
                print(f"{self._COLOR_GREEN}  {i:3d}  {line[:66]}{self._COLOR_RESET}")  # Limit line width
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
        # If auto_approve is set in context, skip user prompts unless deleting without --yes.
        if context and context.auto_approve:
            if tool_name != "delete_file" or getattr(config, "EXPLICIT_YES", False):
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
        python_tools = [
            'rewrite_python_imports',
            'rewrite_python_keyword_args',
            'rename_imported_symbols',
            'move_imported_symbols',
            'rewrite_python_function_parameters',
        ]
        target_files_for_tools = _extract_target_files_from_description(task.description)
        include_python_tools = any(
            path.lower().endswith((".py", ".pyi")) for path in target_files_for_tools
        )

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
                'replace_in_file',
                'apply_patch',
                'write_file',
                'copy_file',
                'move_file',
            ]
            if include_python_tools:
                tool_names = python_tools + tool_names
        elif task.action_type == "refactor":
            # Refactoring may need to create or modify files
            tool_names = [
                'write_file',
                'apply_patch',
                'replace_in_file',
                'copy_file',
                'move_file',
            ]
            if include_python_tools:
                tool_names = python_tools + tool_names
        elif task.action_type in {"move", "rename"}:
            # Move/rename should only use move_file to prevent accidental rewrites.
            tool_names = ['move_file']
        else:
            # Unknown action types get all tools (fallback)
            tool_names = ['write_file', 'replace_in_file', 'create_directory', 'copy_file', 'move_file']

        available_tools = [tool for tool in all_tools if tool['function']['name'] in tool_names]
        recovery_allowed_tools = list(tool_names) if tool_names else [t["function"]["name"] for t in available_tools]
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

        # PRIORITY 1 FIX: Mandatory file reading for edit/refactor tasks
        # For edit/refactor tasks, read target files and include their content
        # This ensures the LLM has the exact file content for replace_in_file
        file_content_section = ""
        if task.action_type in ("edit", "refactor") and not _task_is_command_only(task.description or ""):
            target_files = _extract_target_files_from_description(task.description)

            # MANDATORY: EDIT tasks must identify target files
            if not target_files:
                error_msg = (
                    f"EDIT task must specify target file path in description. "
                    f"Task: '{task.description[:100]}...' does not mention any file to edit. "
                    f"Include file path like 'edit app.js' or 'update package.json'."
                )
                print(f"  [ERROR] {error_msg}")
                if self.should_attempt_recovery(task, context):
                    self.request_replan(
                        context,
                        reason="EDIT task missing target file specification",
                        detailed_reason=(
                            f"{error_msg}\n\n"
                            "RECOVERY: Ensure the task description explicitly mentions the file path to edit. "
                            "Examples: 'edit src/app.js to add routes', 'update package.json to add lint script'. "
                            "If creating a new file, use action_type='add' instead of 'edit'."
                        )
                    )
                    return self.make_recovery_request("missing_target_file", error_msg)
                return self.make_failure_signal("missing_target_file", error_msg)

            # MANDATORY: Read target files (don't proceed without content)
            file_contents = []
            files_read_successfully = []
            files_failed_to_read = []

            for file_path in target_files[:3]:  # Limit to 3 files to avoid context overflow
                content = _read_file_content_for_edit(file_path)
                if content:
                    file_contents.append(f"=== ACTUAL FILE CONTENT: {file_path} ===\n{content}\n=== END OF {file_path} ===")
                    files_read_successfully.append(file_path)
                    print(f"  -> Including actual content of {file_path} for edit context")
                else:
                    files_failed_to_read.append(file_path)
                    print(f"  [WARN] Cannot read target file: {file_path}")

            # Fail fast if no files could be read successfully
            if not files_read_successfully and target_files:
                primary_file = target_files[0]
                error_msg = (
                    f"Cannot read target file '{primary_file}' for EDIT task. "
                    f"File may not exist or is unreadable."
                )
                print(f"  [ERROR] {error_msg}")
                if self.should_attempt_recovery(task, context):
                    self.request_replan(
                        context,
                        reason="Target file not found for EDIT",
                        detailed_reason=(
                            f"{error_msg}\n\n"
                            f"RECOVERY: If '{primary_file}' does not exist yet, use action_type='add' to create it. "
                            f"If the file exists but has a different path, verify the correct path using 'read_file' or 'list_dir'. "
                            f"Do NOT proceed with EDIT action on non-existent files."
                        )
                    )
                    return self.make_recovery_request("file_not_found", error_msg)
                return self.make_failure_signal("file_not_found", error_msg)

            # Warn if some files couldn't be read
            if files_failed_to_read:
                print(f"  [WARN] Could not read {len(files_failed_to_read)} file(s): {', '.join(files_failed_to_read)}")
                print(f"  [WARN] Proceeding with {len(files_read_successfully)} successfully read file(s)")

            # Include file content in prompt
            if file_contents:
                separator = "=" * 70
                file_content_section = f"\n\n{separator}\n"
                file_content_section += "ACTUAL FILE CONTENT TO EDIT (USE THIS AS SOURCE FOR 'find' PARAMETER)\n"
                file_content_section += f"{separator}\n\n"
                file_content_section += "\n\n".join(file_contents)
                file_content_section += f"\n\n{separator}\n"
                file_content_section += (
                    "CRITICAL INSTRUCTIONS FOR replace_in_file:\n"
                    "1. The 'find' parameter MUST be copied CHARACTER-FOR-CHARACTER from the content above\n"
                    "2. Include 2-3 lines of context BEFORE and AFTER the line you want to change\n"
                    "3. DO NOT modify spacing, tabs, or line endings when copying the 'find' text\n"
                    "4. DO NOT type from memory - COPY the exact text you see above\n"
                    "5. If the text you need to edit is NOT visible above, use write_file instead\n"
                    "6. Verify your 'find' text appears EXACTLY in the file content above before submitting\n"
                    f"{separator}\n"
                )

        # Select system prompt based on ultrathink mode
        system_prompt = CODE_WRITER_SYSTEM_PROMPT
        if config.ULTRATHINK_MODE == "on":
            system_prompt = ULTRATHINK_CODE_WRITER_PROMPT
            print("  🧠 ULTRATHINK MODE ENABLED - Using enhanced reasoning prompt")

        messages = [
            {"role": "system", "content": system_prompt},
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
                                        # First failure: suggest using write_file for more reliable replacement
                                        noop_msg = (
                                            f"{noop_msg}\n\n"
                                            f"RECOVERY STEP 1 (Recommended): Switch to write_file tool instead.\n"
                                            f"- Read the entire current file content\n"
                                            f"- Make the necessary changes to the content\n"
                                            f"- Use write_file to replace the entire file with the modified content\n"
                                            f"This is MORE RELIABLE than replace_in_file for complex changes.\n\n"
                                            f"Alternative: Verify the exact 'find' text (character-for-character) from the file content provided, "
                                            f"including ALL whitespace and indentation, then retry replace_in_file."
                                        )
                                    elif consecutive_replace_failures >= 2:
                                        # Second+ failure: strongly recommend write_file
                                        noop_msg = (
                                            f"{noop_msg}\n\n"
                                            f"RECOVERY STEP 2 (MANDATORY): You MUST use write_file instead of replace_in_file.\n"
                                            f"replace_in_file has failed {consecutive_replace_failures} times. The 'find' pattern is not matching.\n"
                                            f"REQUIRED ACTION:\n"
                                            f"1. Request read_file for the target file to get complete current content\n"
                                            f"2. Apply your changes to that content\n"
                                            f"3. Use write_file with the complete modified content\n"
                                            f"DO NOT attempt replace_in_file again - it will fail."
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
                    retried = False
                    recovered = recover_tool_call_from_text(
                        response.get("message", {}).get("content", ""),
                        allowed_tools=recovery_allowed_tools,
                    )
                    if not recovered:
                        recovered = recover_tool_call_from_text_lenient(
                            response.get("message", {}).get("content", ""),
                            allowed_tools=recovery_allowed_tools,
                        )
                        if recovered:
                            print("  [WARN] CodeWriterAgent: using lenient tool call recovery from text output")
                    if not recovered:
                        raw_content = response.get("message", {}).get("content", "") if isinstance(response, dict) else ""
                        if raw_content:
                            print("  [WARN] CodeWriterAgent: attempting tool call repair from text output")
                        recovered = self._retry_with_tool_call_repair(
                            messages,
                            raw_content,
                            allowed_tools=recovery_allowed_tools,
                            tools=available_tools,
                        )
                    if not recovered:
                        recovered = retry_tool_call_with_response_format(
                            messages,
                            available_tools,
                            allowed_tools=recovery_allowed_tools,
                        )
                        if recovered:
                            retried = True
                            print(f"  -> Retried tool call with JSON format: {recovered.name}")
                    if not recovered:
                        recovered = self._retry_with_diff_or_file(
                            messages,
                            allowed_tools=recovery_allowed_tools,
                        )
                    if recovered:
                        tool_name = recovered.name
                        arguments = recovered.arguments
                        if not tool_name:
                            return self.make_failure_signal("missing_tool", "Recovered tool call missing name")
                        if not arguments:
                            return self.make_failure_signal("missing_tool_args", "Recovered tool call missing arguments")
                        if not retried:
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
                                    recovery_key = f"replace_noop_write::{task.task_id or 'unknown'}::{arguments.get('path', '')}"
                                    already_attempted = context.agent_state.get(recovery_key, False)
                                    if not already_attempted:
                                        context.set_agent_state(recovery_key, True)
                                        recovered = self._retry_with_write_file(
                                            messages,
                                            allowed_tools=recovery_allowed_tools,
                                        )
                                        if recovered and recovered.name == "write_file":
                                            tool_name = recovered.name
                                            arguments = recovered.arguments
                                            self._display_change_preview(tool_name, arguments)

                                            file_path = arguments.get("path") or arguments.get("dest") or "unknown"
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
                                                return self.make_failure_signal("invalid_tool_args", arg_msg)

                                            print(f"  Applying {tool_name} to {arguments.get('path', 'file')}...")
                                            raw_result = execute_tool(tool_name, arguments, agent_name="code_writer")
                                            has_error, error_msg = self._tool_result_has_error(raw_result)
                                            if has_error:
                                                print(f"  Tool reported error: {error_msg}")
                                                return self.make_failure_signal("tool_error", error_msg)

                                            is_noop, noop_msg = self._tool_result_is_noop(tool_name, raw_result)
                                            if is_noop:
                                                print(f"  Tool made no changes: {noop_msg}")
                                                return self.make_failure_signal("tool_noop", noop_msg)

                                            print(f"  ✓ Successfully applied {tool_name}")
                                            return build_subagent_output(
                                                agent_name="CodeWriterAgent",
                                                tool_name=tool_name,
                                                tool_args=arguments,
                                                tool_output=raw_result,
                                                context=context,
                                                task_id=task.task_id,
                                            )

                                    # Track consecutive replace_in_file failures to escalate recovery suggestions
                                    consecutive_replace_failures = context.agent_state.get("consecutive_replace_failures", 0)
                                    consecutive_replace_failures += 1
                                    context.set_agent_state("consecutive_replace_failures", consecutive_replace_failures)

                                    # Escalate suggestions based on failure count
                                    if consecutive_replace_failures == 1:
                                        # First failure: suggest using write_file for more reliable replacement
                                        noop_msg = (
                                            f"{noop_msg}\n\n"
                                            f"RECOVERY STEP 1 (Recommended): Switch to write_file tool instead.\n"
                                            f"- Read the entire current file content\n"
                                            f"- Make the necessary changes to the content\n"
                                            f"- Use write_file to replace the entire file with the modified content\n"
                                            f"This is MORE RELIABLE than replace_in_file for complex changes.\n\n"
                                            f"Alternative: Verify the exact 'find' text (character-for-character) from the file content provided, "
                                            f"including ALL whitespace and indentation, then retry replace_in_file."
                                        )
                                    elif consecutive_replace_failures >= 2:
                                        # Second+ failure: strongly recommend write_file
                                        noop_msg = (
                                            f"{noop_msg}\n\n"
                                            f"RECOVERY STEP 2 (MANDATORY): You MUST use write_file instead of replace_in_file.\n"
                                            f"replace_in_file has failed {consecutive_replace_failures} times. The 'find' pattern is not matching.\n"
                                            f"REQUIRED ACTION:\n"
                                            f"1. Request read_file for the target file to get complete current content\n"
                                            f"2. Apply your changes to that content\n"
                                            f"3. Use write_file with the complete modified content\n"
                                            f"DO NOT attempt replace_in_file again - it will fail."
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
