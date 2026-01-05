import json
from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools
from rev.llm.client import ollama_chat
from rev.core.context import RevContext
from rev.execution.safety import is_scary_operation, prompt_scary_operation
from difflib import unified_diff
from typing import Any, Dict, List, Optional, Tuple, Sequence
import re
from pathlib import Path

from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient, RecoveredToolCall
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev.tools.registry import execute_tool as execute_registry_tool
from rev.tools import file_ops
from rev import config
from rev.run_log import write_run_log_line
from rev.execution.ultrathink_prompts import ULTRATHINK_CODE_WRITER_PROMPT
from rev.tools.workspace_resolver import resolve_workspace_path


def _looks_like_code_reference(text: str, context: str = "") -> bool:
    """Check if text looks like a code reference rather than a file path.

    Args:
        text: The candidate string (e.g., "app.listen", "src/file.ts")
        context: Surrounding text for additional context clues

    Returns:
        True if this is likely a code reference, not a file path
    """
    if not text:
        return False

    # Has path separators? Likely a real file path
    has_path_sep = ('/' in text or '\\' in text)
    if has_path_sep:
        return False  # src/file.ts is a file path

    # Count dots
    dot_count = text.count('.')

    # 2+ dots without path separators = definitely code reference
    # Examples: api.interceptors.request, express.json.stringify
    if dot_count >= 2:
        return True

    # For single-dot patterns, check additional signals
    if dot_count == 1:
        # Split into parts
        parts = text.split('.')
        if len(parts) == 2:
            name, extension = parts

            # 1. Check if "name" is a common variable/object name pattern
            # This catches: app.listen, express.json, console.log, test.environment, etc.
            common_var_names = {
                'app', 'obj', 'this', 'self', 'that', 'req', 'res',
                'ctx', 'config', 'options', 'params', 'data', 'server',
                'client', 'router', 'express', 'fastify', 'koa',
                'console', 'process', 'window', 'document', 'global',
                'module', 'exports', 'require', 'import', 'JSON',
                'Math', 'Date', 'Array', 'Object', 'String', 'Number',
                'Promise', 'Error', 'Buffer',
                'test', 'tests', 'env', 'environment', 'settings',
                'props', 'state', 'store', 'theme', 'user', 'session'
            }
            if name.lower() in common_var_names or name in common_var_names:
                return True

            # 2. Check for common method/property names
            # This catches cases where variable name isn't in the list above
            common_code_names = {
                'listen', 'main', 'module', 'exports', 'require', 'import',
                'prototype', 'constructor', 'toString', 'valueOf',
                'length', 'push', 'pop', 'shift', 'map', 'filter',
                'reduce', 'forEach', 'find', 'includes',
                'log', 'error', 'warn', 'info', 'debug',
                'parse', 'stringify', 'join', 'split',
                'get', 'set', 'post', 'put', 'delete', 'patch',
                'use', 'apply', 'call', 'bind', 'then', 'catch',
                'next', 'send', 'status', 'text',
                'locals', 'session', 'cookies', 'query', 'params',
                'body', 'headers', 'path', 'url', 'method',
                'environment', 'timeout', 'retries', 'coverage', 'globals',
                'config', 'name', 'value', 'type', 'id', 'key'
            }
            if extension.lower() in common_code_names:
                return True

            # 3. Check context for code-related keywords
            if context:
                context_lower = context.lower()
                code_keywords = [
                    'call', 'method', 'function', 'property', 'instance',
                    'guard', 'wrap', 'invoke', 'execute', 'trigger',
                    'behind', 'inside', 'within', 'unconditional',
                    'removing', 'guarding', 'middleware'
                ]
                if any(keyword in context_lower for keyword in code_keywords):
                    return True

            # 4. Check if this is a file extension (after ruling out code patterns)
            # Only check file extensions as a last resort to avoid false positives
            common_file_extensions = {
                'js', 'ts', 'jsx', 'tsx', 'py', 'java', 'c', 'cpp', 'h', 'hpp',
                'cs', 'go', 'rs', 'rb', 'php', 'swift', 'kt', 'scala',
                'json', 'yaml', 'yml', 'toml', 'xml', 'html', 'css', 'scss', 'sass',
                'md', 'txt', 'conf', 'cfg', 'ini', 'env',
                'vue', 'svelte', 'astro',
                'sql', 'prisma', 'graphql', 'proto',
                'sh', 'bash', 'ps1', 'bat', 'cmd'
            }
            # Special check: if it's a known file pattern like "package.json", "tsconfig.json"
            # these should be treated as files
            known_config_files = {
                'package', 'tsconfig', 'jsconfig', 'vite.config', 'vitest.config',
                'jest.config', 'webpack.config', 'rollup.config', 'babel.config',
                '.eslintrc', 'prettier.config', 'tailwind.config'
            }
            if name.lower() in known_config_files and extension.lower() in common_file_extensions:
                return False  # This is a config file, not code

            # If extension is a file extension and we haven't identified it as code, it's a file
            if extension.lower() in common_file_extensions:
                return False

    return False


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
    # But exclude code references like `api.interceptors.request.use` or `app.listen`
    backtick_pattern = r'`([^`]+\.\w+)`'
    for match in re.finditer(backtick_pattern, description, re.IGNORECASE):
        candidate = match.group(1)
        # Extract context around the match (50 chars before and after)
        context_start = max(0, match.start() - 50)
        context_end = min(len(description), match.end() + 50)
        context = description[context_start:context_end]
        # Filter out code references
        if _looks_like_code_reference(candidate, context):
            continue
        paths.append(candidate)

    # Match quoted paths like "src/module/file.ext" (any extension)
    quote_pattern = r'"([^"]+\.\w+)"'
    for match in re.finditer(quote_pattern, description, re.IGNORECASE):
        candidate = match.group(1)
        if candidate in paths:
            continue
        # Extract context around the match
        context_start = max(0, match.start() - 50)
        context_end = min(len(description), match.end() + 50)
        context = description[context_start:context_end]
        if _looks_like_code_reference(candidate, context):
            continue
        paths.append(candidate)

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
        # Extract context around the match for code reference detection
        context_start = max(0, match.start() - 50)
        context_end = min(len(description), match.end() + 50)
        context = description[context_start:context_end]
        # Skip code references (check with context)
        if _looks_like_code_reference(candidate, context):
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
        # Check for file-related verbs in preceding context
        verb_context_start = max(0, match.start() - 25)
        verb_context = description[verb_context_start:match.start()]
        if verb_hint.search(verb_context):
            paths.append(candidate)

    return paths


def _targets_exist(paths: list[str]) -> bool:
    """Return True if any provided path exists as a file in the workspace."""
    for raw in paths:
        if not raw:
            continue
        try:
            resolved = resolve_workspace_path(raw).abs_path
            if resolved.is_file():
                return True
        except Exception:
            continue
    return False


def _merge_tool_schemas(primary: Sequence[Dict[str, Any]], fallback: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge tool schema lists, preserving order and de-duplicating by tool name."""
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for tool in list(primary) + list(fallback):
        if not isinstance(tool, dict):
            continue
        name = tool.get("function", {}).get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if name in seen:
            continue
        seen.add(name)
        merged.append(tool)
    return merged


def _detect_path_conflict(path_str: str) -> Optional[str]:
    """
    Detect common path conflicts such as creating both <name>.ts and <name>/index.ts.
    Returns a human-readable warning if a conflict is found.
    """
    if not path_str:
        return None
    try:
        base = Path(config.ROOT) / path_str
    except Exception:
        return None

    # If creating a file like foo.ts and a directory foo/ already exists with index.* inside, warn.
    if base.suffix:
        stem = base.with_suffix("")
        dir_candidate = stem
        if dir_candidate.is_dir():
            index_files = list(dir_candidate.glob("index.*"))
            if index_files:
                return (
                    f"Path conflict: '{path_str}' overlaps with existing directory '{dir_candidate}' "
                    "that already contains an index.* file. Choose a single entry point."
                )
    # If creating a directory and a file with same stem exists, warn.
    if not base.suffix:
        file_candidate_ts = base.with_suffix(".ts")
        file_candidate_js = base.with_suffix(".js")
        for file_candidate in (file_candidate_ts, file_candidate_js):
            if file_candidate.is_file():
                return (
                    f"Path conflict: target directory '{path_str}' overlaps with existing file '{file_candidate.name}'. "
                    "Avoid creating both a file and a directory with the same name."
                )
    return None


def _read_file_content_for_edit(file_path: str, max_lines: int = 2000) -> str | None:
    """Read file content to include in edit context.

    Returns the file content or None if the file cannot be read.

    For files over max_lines, falls back to using write_file strategy instead of replace_in_file.
    NOTE: Empty files are considered readable; callers should treat an empty string as valid content.
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
        if content is not None:
            return content

        # Fallback: resolve relative path against workspace root when workdir is scoped.
        try:
            candidate = Path(file_path)
            if not candidate.is_absolute():
                root_path = Path(config.ROOT)
                alt = root_path / candidate
                content = _try_read(str(alt))
                if content is not None:
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

CODE_WRITER_SYSTEM_PROMPT = """You are a specialized Code Writer agent. Your sole purpose is to execute a single coding task by calling the ONLY available tool.

âš ï¸ CRITICAL: TOOL EXECUTION IS MANDATORY âš ï¸
You MUST call a tool. Do NOT return text or explanations. 

TOOL SELECTION RULES:
1.  For EDITING existing files: You MUST use `apply_patch` or `replace_in_file`. 
2.  Do NOT use `write_file` to overwrite existing files; it will be rejected. 
3.  Use `apply_patch` for any multi-line change. Use `replace_in_file` ONLY for small, exact string swaps.

`apply_patch` RULES:
- Provide a standard unified diff (---/+++/@@).
- Ensure context lines match the provided file content EXACTLY.
- Keep patches minimal to avoid truncation.

`replace_in_file` RULES:
- The `find` string must be an EXACT, character-for-character match (including whitespace).
- Include 2-3 lines of context in `find` to ensure uniqueness.

Your response must be ONLY a JSON tool call. No markdown fences.
"""

def _is_path_valid_for_task(path_str: str, task: Task) -> Tuple[bool, str]:
    """Check if the provided path is reasonable for the given task."""
    if not path_str or path_str == "unknown":
        return True, ""

    # 1. Use the core code reference check
    from rev.core.tool_call_recovery import _looks_like_code_reference
    if _looks_like_code_reference(path_str):
        return False, f"Path '{path_str}' looks like a code reference, not a file path."

    # 2. Check if the path is mentioned in the task description
    desc = (task.description or "").lower()
    path_lower = path_str.lower().replace('\\', '/')
    filename = Path(path_str).name.lower()
    
    # Extract mentioned files from description
    mentioned = [p.lower().replace('\\', '/') for p in _extract_target_files_from_description(task.description)]
    
    if path_lower in mentioned or filename in [Path(p).name for p in mentioned]:
        return True, ""

    # 3. If not mentioned, check if it already exists
    try:
        resolved = resolve_workspace_path(path_str).abs_path
        if resolved.exists():
            return True, ""
    except:
        pass

    # 4. Special cases: some tasks create new files without explicit paths in description
    # but they usually follow a pattern. If it's a completely new path not in desc, be suspicious.
    if task.action_type == "add" and any(token in desc for token in ("create", "add", "new", "file")):
        # allow creation if it's in a reasonable directory
        if any(path_str.startswith(d) for d in ("src/", "tests/", "prisma/", "public/")):
            return True, ""

    return False, f"Path '{path_str}' is not mentioned in the task and does not exist. It may be a hallucination."


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

    def _record_tool_event(
        self,
        task: Task,
        context: RevContext,
        tool_name: str,
        tool_args: Dict[str, Any],
        raw_result: str,
    ) -> None:
        """Record a tool event even when the overall task fails or requests recovery."""
        if not tool_name or not isinstance(tool_name, str):
            return
        if not hasattr(task, "tool_events") or task.tool_events is None:
            task.tool_events = []

        safe_args: Dict[str, Any] = tool_args if isinstance(tool_args, dict) else {"args": tool_args}

        try:
            payload = json.loads(
                build_subagent_output(
                    agent_name="CodeWriterAgent",
                    tool_name=tool_name,
                    tool_args=safe_args,
                    tool_output=raw_result,
                    context=context,
                    task_id=task.task_id,
                )
            )
            evidence = payload.get("evidence") if isinstance(payload, dict) else None
            artifact_ref = None
            summary = None
            if isinstance(evidence, list) and evidence and isinstance(evidence[0], dict):
                artifact_ref = evidence[0].get("artifact_ref")
                summary = evidence[0].get("summary")
            task.tool_events.append(
                {
                    "tool": tool_name,
                    "args": safe_args,
                    "raw_result": raw_result,
                    "artifact_ref": artifact_ref,
                    "summary": summary,
                }
            )
        except Exception:
            task.tool_events.append(
                {
                    "tool": tool_name,
                    "args": safe_args,
                    "raw_result": raw_result,
                }
            )

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

        # CRITICAL GUARD: Enforce research before add/edit operations
        if task.action_type in ("add", "edit"):
            recent_tasks = context.agent_state.get("recent_tasks") or []
            research_keywords = ["list_dir", "tree_view", "read", "search", "listing", "found"]
            has_research = any(
                any(kw in str(prev_task).lower() for kw in research_keywords)
                for prev_task in recent_tasks[-10:]
            )

            if not has_research:
                print(f"  [RESEARCH_GUARD] WARNING: {task.action_type.upper()} action without prior research!")
                print(f"  [RESEARCH_GUARD] Forcing research step before proceeding...")
                signature = f"missing_research::{task.action_type}::{(task.description or '').strip().lower()}"
                should_inject = not bool(context.get_agent_state(signature, False))
                if should_inject:
                    context.set_agent_state(signature, True)
                    target_files = _extract_target_files_from_description(task.description or "")
                    target_hint = ""
                    if target_files:
                        target_hint = f" Confirm whether these targets exist: {', '.join(target_files[:3])}."
                    research_desc = (
                        "Inspect repository structure with tree_view (max depth 2) or list_dir to "
                        "locate target files for the pending write task."
                        f"{target_hint}"
                    )
                    context.add_agent_request(
                        "INJECT_TASKS",
                        {"tasks": [Task(description=research_desc, action_type="read")]},
                    )
                return json.dumps({
                    "skipped": True,
                    "reason": "missing_research",
                    "action": task.action_type,
                    "description": task.description,
                    "injected": should_inject,
                })

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        # Determine appropriate tools
        all_tools = get_available_tools()
        
        if task.action_type == "create_directory":
            tool_names = ['create_directory']
        elif task.action_type == "add":
            # ADD gets write_file plus patching tools (in case file exists)
            tool_names = ['write_file', 'apply_patch', 'replace_in_file']
        elif task.action_type == "edit":
            # For EDIT, we prefer patching tools.
            tool_names = ['apply_patch', 'replace_in_file', 'copy_file', 'move_file']
            
            # Only allow write_file for EDIT if the file DOES NOT exist or is empty
            # (Basically treating it like an ADD if it's new)
            try:
                target_paths = _extract_target_files_from_description(task.description)
                if target_paths:
                    resolved = resolve_workspace_path(target_paths[0]).abs_path
                    if not resolved.exists() or resolved.stat().st_size == 0:
                        tool_names.append('write_file')
            except:
                pass
        elif task.action_type in {"move", "rename"}:
            tool_names = ['move_file']
        else:
            # General fallback
            tool_names = ['write_file', 'apply_patch', 'replace_in_file', 'create_directory', 'copy_file', 'move_file']

        available_tools = [tool for tool in all_tools if tool['function']['name'] in tool_names]
        recovery_allowed_tools = tool_names

        # Build context and tools
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=tool_names,
            max_tools=len(tool_names),
        )
        if selected_tools:
            available_tools = _merge_tool_schemas(selected_tools, available_tools)

        # Task guidance
        task_guidance = f"Task (action_type: {task.action_type}): {task.description}"
        
        # Mandatory file reading for edits
        file_content_section = ""
        if task.action_type in ("edit", "refactor") and not _task_is_command_only(task.description or ""):
            target_files = _extract_target_files_from_description(task.description)
            if not target_files:
                error_msg = "EDIT task must specify target file path in description."
                print(f"  [ERROR] {error_msg}")
                return self.make_failure_signal("missing_target_file", error_msg)

            file_contents = []
            files_read_successfully = []
            for file_path in target_files[:3]:
                content = _read_file_content_for_edit(file_path)
                if content is not None:
                    file_contents.append(f"=== ACTUAL FILE CONTENT: {file_path} ===\n{content}\n=== END OF {file_path} ===")
                    files_read_successfully.append(file_path)
            
            if not files_read_successfully and target_files:
                error_msg = f"Cannot read target file '{target_files[0]}' for EDIT task."
                print(f"  [ERROR] {error_msg}")
                return self.make_failure_signal("file_not_found", error_msg)

            if file_contents:
                separator = "=" * 70
                file_content_section = f"\n\n{separator}\nACTUAL FILE CONTENT TO EDIT\n{separator}\n\n"
                file_content_section += "\n\n".join(file_contents)
                file_content_section += f"\n\n{separator}\n"

        # LLM Call
        # Force tool calls for write tasks, but relax if previous attempt failed
        tool_choice_mode = "required" if recovery_attempts <= 1 else "auto"

        messages = [
            {"role": "system", "content": CODE_WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": f"{task_guidance}\n\nSelected Context:\n{rendered_context}{file_content_section}"}
        ]

        try:
            response = ollama_chat(
                messages,
                tools=available_tools,
                supports_tools=True,
                tool_choice=tool_choice_mode
            )

            msg = response.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            raw_content = msg.get("content", "")

            tool_name, arguments, error_type, error_detail = None, None, None, None

            # 1. Parse structured tool calls
            if tool_calls:
                tool_call = tool_calls[0]
                tool_name = tool_call.get('function', {}).get('name')
                arguments_str = tool_call.get('function', {}).get('arguments')
                if isinstance(arguments_str, dict):
                    arguments = arguments_str
                else:
                    try:
                        arguments = json.loads(arguments_str)
                    except:
                        error_type = "invalid_json"
                        error_detail = "Invalid JSON in arguments"

            # 2. Recovery from text
            if not tool_name or error_type:
                recovered = recover_tool_call_from_text(raw_content, allowed_tools=recovery_allowed_tools)
                if not recovered:
                    recovered = recover_tool_call_from_text_lenient(raw_content, allowed_tools=recovery_allowed_tools)
                if recovered:
                    tool_name, arguments, error_type = recovered.name, recovered.arguments, None
                    print(f"  -> Recovered tool call from text output: {tool_name}")

            # 3. Fallback retries
            if not tool_name and not error_type:
                recovered = self._retry_with_tool_call_repair(messages, raw_content, allowed_tools=recovery_allowed_tools, tools=available_tools)
                if not recovered:
                    recovered = self._retry_with_diff_or_file(messages, allowed_tools=recovery_allowed_tools)
                if recovered:
                    tool_name, arguments = recovered.name, recovered.arguments
                    print(f"  -> Recovered tool call via fallback retry: {tool_name}")
                else:
                    error_type, error_detail = "no_tool_call", "LLM failed to call a tool"

            # 4. Validation and Execution
            if tool_name and not error_type:
                # FOR EDIT TASKS: Enforce no overwrite via write_file
                if task.action_type.lower() == "edit" and tool_name == "write_file":
                    target_path = arguments.get("path") or ""
                    try:
                        resolved = resolve_workspace_path(target_path).abs_path
                        if resolved.exists():
                            msg = f"write_file not allowed for edit tasks on existing file: {target_path}"
                            if self.should_attempt_recovery(task, context):
                                self.request_replan(context, reason="write_file_not_allowed_for_edit", detailed_reason=msg)
                                return self.make_recovery_request("write_file_not_allowed_for_edit", msg)
                            return self.make_failure_signal("write_file_not_allowed_for_edit", msg)
                    except: pass

                if tool_name in tool_names:
                    self._display_change_preview(tool_name, arguments)
                    file_path = arguments.get("path") or arguments.get("dest") or "unknown"
                    
                    # VALIDATE PATH
                    is_valid_path, path_error = _is_path_valid_for_task(file_path, task)
                    if not is_valid_path:
                        print(f"  ✗ Invalid path: {path_error}")
                        if self.should_attempt_recovery(task, context):
                            self.request_replan(context, reason="invalid_path", detailed_reason=path_error)
                            return self.make_recovery_request("invalid_path", path_error)
                        return self.make_failure_signal("invalid_path", path_error)

                    conflict = _detect_path_conflict(file_path)
                    if conflict: print(f"  [WARN] {conflict}")

                    if not self._prompt_for_approval(tool_name, file_path, context):
                        print(f"  ✗ Change rejected by user")
                        return "[USER_REJECTED] Change was not approved by user"

                ok_args, arg_msg = self._validate_tool_args(tool_name, arguments)
                if not ok_args:
                    print(f"  ✗ Invalid tool args: {arg_msg}")
                    return self.make_failure_signal("invalid_tool_args", arg_msg)

                print(f"  ⏳ Applying {tool_name} to {arguments.get('path', 'file')}...")
                raw_result = execute_tool(tool_name, arguments, agent_name="code_writer")

                has_err, tool_err = self._tool_result_has_error(raw_result)
                if has_err:
                    self._record_tool_event(task, context, tool_name, arguments, raw_result)
                    print(f"  ✗ Tool error: {tool_err}")
                    if self.should_attempt_recovery(task, context):
                        # Enhanced guidance for apply_patch failure
                        if tool_name == "apply_patch":
                            tool_err += "\n\nRECOVERY: Patch failed. Try using replace_in_file for smaller changes or write_file to rewrite the entire file."
                        self.request_replan(context, reason="tool_error", detailed_reason=tool_err)
                        return self.make_recovery_request("tool_error", tool_err)
                    return self.make_failure_signal("tool_error", tool_err)

                is_noop, noop_msg = self._tool_result_is_noop(tool_name, raw_result)
                if is_noop:
                    self._record_tool_event(task, context, tool_name, arguments, raw_result)
                    print(f"  ? Tool no-op: {noop_msg}")
                    return self.make_failure_signal("tool_noop", noop_msg)

                self._record_tool_event(task, context, tool_name, arguments, raw_result)
                print(f"  ✓ Successfully applied {tool_name}")
                return build_subagent_output(
                    agent_name="CodeWriterAgent",
                    tool_name=tool_name,
                    tool_args=arguments,
                    tool_output=raw_result,
                    context=context,
                    task_id=task.task_id,
                )

            # 5. Handle Failures
            print(f"  [WARN] CodeWriterAgent: {error_detail or 'Tool call generation failed'}")
            if self.should_attempt_recovery(task, context):
                self.request_replan(context, reason="tool_generation_failed", detailed_reason=error_detail)
                return self.make_recovery_request(error_type, error_detail)
            return self.make_failure_signal(error_type, error_detail)

        except Exception as e:
            print(f"  [WARN] CodeWriterAgent exception: {e}")
            if self.should_attempt_recovery(task, context):
                return self.make_recovery_request("exception", str(e))
            return self.make_failure_signal("exception", str(e))

            