"""
Execution mode implementations for sequential and concurrent task execution.

This module provides the execution phase functionality that runs planned tasks
with support for sequential and concurrent execution modes, including tool
invocation and error handling.

Performance optimizations:
- Message history management to prevent unbounded growth (60-80% token reduction)
- Sliding window keeps recent context while summarizing old messages
"""

import json
import re
import threading
from collections import OrderedDict
from typing import Dict, Any, List, Optional, Tuple

from rev.models.task import ExecutionPlan, Task, TaskStatus
from rev.execution.state_manager import StateManager
from rev.tools.registry import execute_tool
from rev.llm.client import ollama_chat
from rev.config import (
    get_system_info_cached,
    get_escape_interrupt,
    set_escape_interrupt,
    MAX_READ_FILE_PER_TASK,
    MAX_SEARCH_CODE_PER_TASK,
    MAX_RUN_CMD_PER_TASK,
    MAX_EXECUTION_ITERATIONS,
    MAX_TASK_ITERATIONS,
    CONTEXT_WINDOW_HISTORY,
)
from rev import config
from rev.execution.safety import (
    format_operation_description,
    is_scary_operation,
    prompt_scary_operation,
)
from rev.execution.reviewer import review_action, display_action_review, format_review_feedback_for_llm
from rev.execution.session import SessionTracker, create_message_summary_from_history
from rev.debug_logger import get_logger

EXECUTION_SYSTEM = """You are an autonomous coding agent that executes planned tasks using tools.

System context:
- Use the provided OS details to choose correct commands and paths.

How to work:
1) Understand the current task and its action_type.
2) Gather minimal context with tools (list_dir, search_code, read_file) as needed.
3) If action_type is "add" or "edit", make the change with write_file/apply_patch.
4) If action_type is "review", do not modify files; summarize findings and move on.
5) If action_type is "test", run tests via run_cmd/run_tests and report results.

Tool discipline:
- Do not call the same tool with identical arguments twice in a row.
- Avoid repeated exploration loops; if searches fail, change the query once, then decide and act.

Patch requirements:
- apply_patch accepts only unified diffs (diff --git or ---/+++ with @@ hunks).
- Do not output '*** Begin Patch' blocks.

Completion:
- Reply with TASK_COMPLETE only after the current task’s goal is satisfied (and tests run when required)."""


CODING_EXECUTION_SUFFIX = """
You are executing CODE and TEST tasks.

When the task involves code changes:

1. Understand first:
   - Use search_code, list_dir, tree_view, and read_file to inspect the relevant code.
2. Make changes safely:
   - Use apply_patch with unified diffs instead of overwriting files blindly.
   - Do NOT output '*** Begin Patch' blocks; use unified diffs (diff --git or ---/+++ with @@ hunks).
   - Keep changes minimal, consistent, and well-structured.
   - If a file/class/function is missing, create it immediately instead of re-listing directories.
   - If resource or iteration budgets start warning, pause further exploration and finish the best viable patch.
3. Validate:
   - Use run_tests with an appropriate command (e.g. 'pytest -q') AFTER making changes.
   - If tests fail, inspect the output and fix the issues before declaring completion.
4. Git hygiene:
   - Use git_diff to inspect your changes.
   - Do NOT force-push or run destructive git commands without a clear reason.

You MUST NOT respond with TASK_COMPLETE until:
- All intended code changes for this task are implemented, AND
- Relevant tests have been run, AND
- Tests either pass OR you have a clear, explicit reason why tests cannot yet pass.
"""


TEST_WRITER_SYSTEM = """
You are an expert test engineer.

Given:
- A description of the user's requested change
- A summary of the codebase
- Validation or test failures

Your job is to:
1. Propose or update automated tests that clearly exercise the behavior.
2. Use existing test patterns and frameworks in this repo when possible.
3. Write tests that are small, focused, and easy to debug.

Use tools such as read_file, list_dir, search_code, write_file, and run_tests
to locate existing tests, add new test files, and verify that tests run.

When you create or update tests, explain briefly:
- Which behavior is being tested
- Where the tests were added or modified

Do not change production code in this mode unless it is required to fix a
test that cannot be executed otherwise.
"""

DEFAULT_SNIPPET_WINDOW = 20  # ~40-50 lines of context per match
MAX_SNIPPETS_FOR_CONTEXT = 5


def _summarize_plan(plan: ExecutionPlan, max_items: int = 5) -> str:
    """Create a short summary of the execution plan."""
    if not plan or not plan.tasks:
        return "No tasks provided."

    parts = []
    for idx, task in enumerate(plan.tasks[:max_items], 1):
        parts.append(f"{idx}. {task.description} ({task.action_type})")

    if len(plan.tasks) > max_items:
        parts.append(f"... {len(plan.tasks) - max_items} more tasks not shown")

    return "\n".join(parts)


class ExecutionContext:
    """Per-run caches and context helpers for the executor."""

    def __init__(self, plan: ExecutionPlan):
        self.plan_summary = _summarize_plan(plan)
        self.code_cache: OrderedDict[str, str] = OrderedDict()
        self.max_code_cache = 32
        self.search_cache: Dict[Tuple[Any, ...], str] = {}
        self.snippet_cache: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        # Track tool calls to detect loops and duplicates
        self.tool_call_history: List[Tuple[str, str]] = []  # (tool_name, args_hash)
        self.max_tool_call_history = 128
        self.recent_actions: List[str] = []  # Human-readable recent actions
        self.exploration_count = 0  # Count of read/search/list calls
        self.edit_count = 0  # Count of write/patch calls
        self.force_edit_warnings = 0  # Count of "force edit" warnings given
        self.exploration_blocked = False  # If True, block exploration tools for edit tasks

        # Session-level tracking (persists across tasks within same run)
        self.session_failed_commands: List[str] = []  # Commands that failed
        self.session_unavailable_paths: List[str] = []  # Paths that don't exist
        self.session_learnings: List[str] = []  # Key learnings from previous tasks
        self.completed_task_summaries: List[str] = []  # What each completed task accomplished

    def get_code(self, path: Optional[str]) -> Optional[str]:
        """Return cached code for a path if available."""
        if not path:
            return None
        with self._lock:
            if path in self.code_cache:
                self.code_cache.move_to_end(path)
                return self.code_cache[path]
            return None

    def set_code(self, path: Optional[str], content: str):
        """Cache code content for a path."""
        if not path:
            return
        with self._lock:
            self.code_cache[path] = content
            self.code_cache.move_to_end(path)
            if len(self.code_cache) > self.max_code_cache:
                self.code_cache.popitem(last=False)

    def get_search(self, key: Tuple[Any, ...]) -> Optional[str]:
        """Return cached search results if available."""
        with self._lock:
            return self.search_cache.get(key)

    def set_search(self, key: Tuple[Any, ...], result: str):
        """Cache search results."""
        with self._lock:
            self.search_cache[key] = result

    def invalidate_code(self, path: Optional[str]):
        """Invalidate cached code for a path."""
        if not path:
            return
        with self._lock:
            self.code_cache.pop(path, None)

    def clear_code_cache(self):
        """Clear code cache (e.g., after broad patches)."""
        with self._lock:
            self.code_cache.clear()

    def add_snippet(self, path: str, start_line: Optional[int], end_line: Optional[int], content: str, max_snippets: int = 8):
        """Store a trimmed snippet for later prompt context."""
        snippet_text = _trim_snippet_content(content)
        snippet = {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "content": snippet_text,
        }
        with self._lock:
            self.snippet_cache.append(snippet)
            self.snippet_cache = self.snippet_cache[-max_snippets:]

    def get_snippets(self) -> List[Dict[str, Any]]:
        """Return a copy of cached snippets."""
        with self._lock:
            return list(self.snippet_cache)

    def _hash_args(self, args: Dict[str, Any]) -> str:
        """Create a stable hash of tool arguments."""
        import hashlib
        # Sort keys for consistent hashing
        sorted_args = json.dumps(args, sort_keys=True, default=str)
        return hashlib.md5(sorted_args.encode()).hexdigest()[:12]

    def is_duplicate_call(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """Check if this exact tool call was already made immediately prior."""
        args_hash = self._hash_args(tool_args)
        call_key = (tool_name, args_hash)
        with self._lock:
            if not self.tool_call_history:
                return False
            return self.tool_call_history[-1] == call_key

    def record_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> None:
        """Record a tool call for deduplication tracking."""
        args_hash = self._hash_args(tool_args)
        call_key = (tool_name, args_hash)

        # Track exploration vs edit operations
        exploration_tools = {"read_file", "search_code", "list_dir", "tree_view", "get_repo_context"}
        edit_tools = {"write_file", "apply_patch"}

        with self._lock:
            self.tool_call_history.append(call_key)
            if len(self.tool_call_history) > self.max_tool_call_history:
                self.tool_call_history.pop(0)

            if tool_name in exploration_tools:
                self.exploration_count += 1
            elif tool_name in edit_tools:
                self.edit_count += 1

            # Record human-readable action (keep last 10)
            action_desc = self._format_action(tool_name, tool_args)
            self.recent_actions.append(action_desc)
            self.recent_actions = self.recent_actions[-10:]

    def _format_action(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        """Format a tool call as a human-readable action."""
        if tool_name == "read_file":
            return f"read_file({tool_args.get('path', '?')})"
        elif tool_name == "search_code":
            pattern = tool_args.get("pattern", "")[:30]
            include = tool_args.get("include", "**/*")
            return f"search_code('{pattern}' in {include})"
        elif tool_name == "list_dir":
            return f"list_dir({tool_args.get('pattern', '?')})"
        elif tool_name == "tree_view":
            return f"tree_view({tool_args.get('path', '.')})"
        elif tool_name == "write_file":
            return f"write_file({tool_args.get('path', '?')})"
        elif tool_name == "apply_patch":
            return "apply_patch(...)"
        else:
            return f"{tool_name}(...)"

    def get_recent_actions_summary(self) -> str:
        """Get a summary of recent actions for context injection."""
        with self._lock:
            if not self.recent_actions:
                return ""
            return "Recent actions: " + " → ".join(self.recent_actions[-5:])

    def is_exploration_heavy(self, threshold: int = 8) -> bool:
        """Check if task has done too much exploration without editing."""
        with self._lock:
            return self.exploration_count >= threshold and self.edit_count == 0

    def detect_loop_pattern(self) -> Optional[str]:
        """Detect if the same tools are being called repeatedly (loop)."""
        with self._lock:
            if len(self.tool_call_history) < 4:
                return None

            # Check last 6 calls for repeated patterns
            recent = self.tool_call_history[-6:]
            tool_names = [t[0] for t in recent]

            # Count occurrences of each tool in recent calls
            from collections import Counter
            counts = Counter(tool_names)

            # If any tool was called 3+ times in last 6 calls, it's a potential loop
            for tool, count in counts.items():
                if count >= 3 and tool in {"search_code", "list_dir", "tree_view", "read_file"}:
                    return f"Detected loop: {tool} called {count} times in last 6 operations"

            return None

    def reset_for_new_task(self) -> None:
        """Reset per-task tracking for a new task."""
        with self._lock:
            self.tool_call_history.clear()
            self.recent_actions.clear()
            self.exploration_count = 0
            self.edit_count = 0
            self.force_edit_warnings = 0
            self.exploration_blocked = False

    def should_block_exploration(self, action_type: str) -> bool:
        """Check if exploration calls should be blocked for edit/add tasks.

        After multiple warnings to make edits, block further exploration
        to force the LLM to take action.
        """
        with self._lock:
            # Only block for edit/add action types
            if action_type not in {"edit", "add"}:
                return False
            return self.exploration_blocked

    def increment_force_edit_warning(self, action_type: str) -> int:
        """Track force edit warnings and enable blocking after enough warnings.

        Returns the current warning count.
        """
        with self._lock:
            self.force_edit_warnings += 1
            # After 2 warnings, block further exploration for edit/add tasks
            if self.force_edit_warnings >= 2 and action_type in {"edit", "add"}:
                self.exploration_blocked = True
            return self.force_edit_warnings

    def record_failed_command(self, cmd: str, error: str) -> None:
        """Record a command that failed (persists across tasks)."""
        with self._lock:
            entry = f"{cmd[:80]}: {error[:100]}"
            if entry not in self.session_failed_commands:
                self.session_failed_commands.append(entry)
                # Keep last 10 failures
                self.session_failed_commands = self.session_failed_commands[-10:]

    def record_unavailable_path(self, path: str) -> None:
        """Record a path that doesn't exist (persists across tasks)."""
        with self._lock:
            if path not in self.session_unavailable_paths:
                self.session_unavailable_paths.append(path)
                # Keep last 15 paths
                self.session_unavailable_paths = self.session_unavailable_paths[-15:]

    def record_learning(self, learning: str) -> None:
        """Record a key learning from task execution (persists across tasks)."""
        with self._lock:
            if learning not in self.session_learnings:
                self.session_learnings.append(learning)
                # Keep last 10 learnings
                self.session_learnings = self.session_learnings[-10:]

    def record_task_completion(self, task_desc: str, summary: str) -> None:
        """Record what a completed task accomplished."""
        with self._lock:
            entry = f"[{task_desc[:50]}]: {summary[:100]}"
            self.completed_task_summaries.append(entry)
            # Keep last 5 task summaries
            self.completed_task_summaries = self.completed_task_summaries[-5:]

    def get_session_context(self) -> str:
        """Get session-level context to inject at start of each task."""
        with self._lock:
            parts = []

            if self.session_unavailable_paths:
                parts.append("UNAVAILABLE PATHS (do not search/read these):")
                for path in self.session_unavailable_paths:
                    parts.append(f"  - {path}")

            if self.session_failed_commands:
                parts.append("\nFAILED COMMANDS (do not retry):")
                for cmd in self.session_failed_commands:
                    parts.append(f"  - {cmd}")

            if self.session_learnings:
                parts.append("\nKEY LEARNINGS FROM PREVIOUS TASKS:")
                for learning in self.session_learnings:
                    parts.append(f"  - {learning}")

            if self.completed_task_summaries:
                parts.append("\nPREVIOUS TASK RESULTS:")
                for summary in self.completed_task_summaries:
                    parts.append(f"  - {summary}")

            return "\n".join(parts) if parts else ""


def _make_search_cache_key(args: Dict[str, Any]) -> Tuple[Any, ...]:
    """Build a stable cache key for search_code calls."""
    return (
        args.get("pattern", ""),
        args.get("include", "**/*"),
        bool(args.get("regex", True)),
        bool(args.get("case_sensitive", False)),
    )


def _has_error_result(result: str) -> bool:
    """Detect if a tool result is an error payload."""
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and "error" in data


def _consume_tool_budget(tool_name: str, counters: Dict[str, int], limits: Dict[str, int]) -> Tuple[bool, str]:
    """Enforce per-task tool budgets."""
    limit = limits.get(tool_name)
    if limit is None:
        return True, ""

    used = counters.get(tool_name, 0)
    if used >= limit:
        return False, f"{tool_name} budget reached for this task ({used}/{limit}); continue without more {tool_name} calls."

    counters[tool_name] = used + 1
    return True, ""


def _trim_snippet_content(content: str, max_chars: int = 2000) -> str:
    """Trim snippet content to a manageable size."""
    if content is None:
        return ""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n...[truncated]..."


def _extract_snippet(content: str, line_number: int, window: int = DEFAULT_SNIPPET_WINDOW) -> Tuple[int, int, str]:
    """Return a snippet window around a line number."""
    lines = content.splitlines()
    if not lines:
        return 1, 1, ""

    center = max(1, line_number)
    start_idx = max(center - window - 1, 0)
    end_idx = min(center + window, len(lines))
    snippet_text = "\n".join(lines[start_idx:end_idx])
    return start_idx + 1, end_idx, _trim_snippet_content(snippet_text)


def _format_snippet_context(exec_context: Optional[ExecutionContext]) -> str:
    """Format cached snippets for inclusion in the LLM prompt."""
    if not exec_context:
        return ""

    snippets = exec_context.get_snippets()
    if not snippets:
        return ""

    snippets = snippets[-MAX_SNIPPETS_FOR_CONTEXT:]
    parts = []
    for snippet in snippets:
        path = snippet.get("path", "")
        start = snippet.get("start_line")
        end = snippet.get("end_line")
        location = path
        if start and end:
            location = f"{path}:{start}-{end}"
        parts.append(f"{location}\n{snippet.get('content', '')}")

    return "\n\n".join(parts)


def _prepare_llm_messages(
    messages: List[Dict],
    exec_context: ExecutionContext,
    tracker: Optional[SessionTracker] = None,
    max_recent: Optional[int] = None,
) -> List[Dict]:
    """Prepare a trimmed, context-rich message list for the LLM."""
    if max_recent is None:
        max_recent = config.CONTEXT_WINDOW_HISTORY
    trimmed = _manage_message_history(messages, max_recent=max_recent, tracker=tracker)
    prepared: List[Dict[str, Any]] = []

    if not trimmed:
        return prepared

    system_msg = trimmed[0] if trimmed and trimmed[0].get("role") == "system" else None
    if system_msg:
        prepared.append({"role": "system", "content": system_msg.get("content", "")})

    context_blocks = []
    if exec_context and exec_context.plan_summary:
        context_blocks.append(f"Plan summary:\n{exec_context.plan_summary}")

    snippet_text = _format_snippet_context(exec_context)
    if snippet_text:
        context_blocks.append(f"Cached code snippets:\n{snippet_text}")

    # Add recent actions to help LLM avoid repeating itself
    if exec_context:
        recent_actions = exec_context.get_recent_actions_summary()
        if recent_actions:
            context_blocks.append(f"⚠️ {recent_actions} - DO NOT repeat these actions.")

    if context_blocks:
        prepared.append({"role": "user", "content": "\n\n".join(context_blocks)})

    start_idx = 1 if system_msg else 0
    for msg in trimmed[start_idx:]:
        content = msg.get("content", "")
        if msg.get("role") == "tool":
            content = _trim_snippet_content(str(content))
        prepared.append({
            "role": msg.get("role"),
            "content": content,
            "name": msg.get("name")
        })

    if tracker:
        tracker.track_messages(len(prepared))

    return prepared


def _augment_search_results(
    search_result: str,
    tool_args: Dict[str, Any],
    exec_context: ExecutionContext,
    tool_limits: Dict[str, int],
    tool_usage: Dict[str, int],
    session_tracker: Optional[SessionTracker],
    debug_logger,
    max_context_matches: int = 5,
) -> str:
    """Add contextual code snippets around search hits."""
    try:
        parsed = json.loads(search_result)
    except json.JSONDecodeError:
        return search_result

    matches = parsed.get("matches", []) or []
    snippets: List[Dict[str, Any]] = []

    for match in matches[:max_context_matches]:
        path = match.get("file")
        line = match.get("line")

        if not path or not isinstance(line, int):
            continue

        content = exec_context.get_code(path)
        used_cache = content is not None

        if content is None:
            allowed, budget_msg = _consume_tool_budget("read_file", tool_usage, tool_limits)
            if not allowed:
                snippets.append({"file": path, "note": budget_msg})
                continue

            content = execute_tool("read_file", {"path": path})
            if session_tracker:
                session_tracker.track_tool_call("read_file", {"path": path})
            if _has_error_result(content):
                snippets.append({"file": path, "note": content})
                continue

            exec_context.set_code(path, content)

        start_line, end_line, snippet_text = _extract_snippet(content, line)
        exec_context.add_snippet(path, start_line, end_line, snippet_text)
        snippets.append({
            "file": path,
            "start_line": start_line,
            "end_line": end_line,
            "snippet": snippet_text,
            "source": "cache" if used_cache else "fresh"
        })

    payload = {
        "pattern": tool_args.get("pattern"),
        "include": tool_args.get("include", "**/*"),
        "truncated": parsed.get("truncated", False),
        "matches": matches[:max_context_matches],
        "context_snippets": snippets,
    }

    if debug_logger:
        debug_logger.log("executor", "SEARCH_CONTEXT", {
            "pattern": tool_args.get("pattern"),
            "matches_considered": min(len(matches), max_context_matches),
            "snippets": len(snippets),
        }, "DEBUG")

    return json.dumps(payload)


def _extract_patch_from_text(content: str) -> Optional[str]:
    """Try to extract a unified diff/patch from free-form text."""
    if not content:
        return None

    # Look for ```diff ... ``` fences
    diff_match = re.search(r"```diff\s+(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if diff_match:
        return diff_match.group(1).strip()

    # Look for raw unified diff markers
    raw_match = re.search(r"^diff --git.*", content, re.DOTALL | re.MULTILINE)
    if raw_match:
        return raw_match.group(0).strip()

    return None


def _looks_like_codex_patch_block(content: str) -> bool:
    """Detect Codex-style apply_patch blocks (*** Begin Patch) which are not git-style diffs."""
    if not content:
        return False
    return "*** Begin Patch" in content and "*** End Patch" in content


def _extract_file_from_text(content: str) -> Optional[Tuple[str, str]]:
    """Extract a full file write (path, content) from fenced code blocks."""
    if not content:
        return None

    fence = re.search(r"```[\w+-]*\s+([\s\S]*?)```", content)
    if not fence:
        return None

    block = fence.group(1)
    lines = block.splitlines()
    if not lines:
        return None

    path = None
    first_line = lines[0].strip()
    path_markers = ("path:", "file:", "filepath:")
    if any(first_line.lower().startswith(marker) for marker in path_markers):
        path = first_line.split(":", 1)[1].strip()
        body = "\n".join(lines[1:])
    elif (
        "." in first_line
        and " " not in first_line
        and first_line.lower().endswith((".py", ".js", ".ts", ".md", ".json", ".yaml", ".yml", ".txt"))
    ):
        path = first_line
        body = "\n".join(lines[1:])
    else:
        return None

    body = body.rstrip("\n")
    if not path or not body:
        return None
    return path, body


def _apply_patch_fallback(
    patch_text: str,
    messages: List[Dict[str, Any]],
    session_tracker: Optional[SessionTracker],
    debug_logger,
    exec_context: Optional[ExecutionContext] = None,
) -> bool:
    """Execute an apply_patch fallback when the model emits text patches."""
    if not patch_text:
        return False

    try:
        result = execute_tool("apply_patch", {"patch": patch_text, "dry_run": False})
        if session_tracker:
            session_tracker.track_tool_call("apply_patch", {"patch": "[text-fallback]"})
        if _has_error_result(result):
            messages.append({
                "role": "tool",
                "name": "apply_patch",
                "content": result
            })
            if debug_logger:
                debug_logger.log("executor", "TEXT_PATCH_APPLIED", {"status": "error"}, "WARNING")
            return False
        messages.append({
            "role": "tool",
            "name": "apply_patch",
            "content": result
        })
        if debug_logger:
            debug_logger.log("executor", "TEXT_PATCH_APPLIED", {"status": "ok"}, "INFO")
        if exec_context:
            exec_context.clear_code_cache()
        return True
    except Exception as exc:  # pragma: no cover - defensive
        if debug_logger:
            debug_logger.log("executor", "TEXT_PATCH_FAILED", {"error": str(exc)}, "ERROR")
        return False


def _apply_text_fallbacks(
    content: str,
    action_type: str,
    messages: List[Dict[str, Any]],
    session_tracker: Optional[SessionTracker],
    exec_context: Optional[ExecutionContext],
    debug_logger,
) -> bool:
    """Try to handle text-only responses by applying patches or writing files."""
    if action_type not in {"add", "edit"}:
        return False

    if _looks_like_codex_patch_block(content):
        messages.append(
            {
                "role": "user",
                "content": (
                    "You provided a patch in Codex '*** Begin Patch' format, which cannot be applied here. "
                    "Use a unified diff (either start with 'diff --git', or provide '---/+++/@@' hunks inside a ```diff``` block)."
                ),
            }
        )
        return False

    text_patch = _extract_patch_from_text(content)
    if text_patch:
        applied = _apply_patch_fallback(text_patch, messages, session_tracker, debug_logger, exec_context)
        if applied:
            return True

    file_payload = _extract_file_from_text(content)
    if file_payload:
        path, body = file_payload
        try:
            result = execute_tool("write_file", {"path": path, "content": body})
            if exec_context:
                exec_context.invalidate_code(path)
                exec_context.set_code(path, body)
            if session_tracker:
                session_tracker.track_tool_call("write_file", {"path": path})
            messages.append({
                "role": "tool",
                "name": "write_file",
                "content": result
            })
            if debug_logger:
                debug_logger.log("executor", "TEXT_WRITE_APPLIED", {"path": path}, "INFO")
            return not _has_error_result(result)
        except Exception as exc:  # pragma: no cover - defensive
            if debug_logger:
                debug_logger.log("executor", "TEXT_WRITE_FAILED", {"error": str(exc)}, "ERROR")
    return False


def _build_task_constraints(task: Task) -> str:
    """Build task-specific constraints to enforce boundaries.

    Args:
        task: The task to build constraints for

    Returns:
        Constraint string to add to task prompt
    """
    action_type = task.action_type.lower()
    constraints = []

    # Action-type specific constraints
    if action_type == "review":
        constraints.append("⚠️ REVIEW TASK: You may ONLY read files and search code. Do NOT write, edit, or modify any files.")
        constraints.append("Expected output: A brief summary (3-5 sentences) of what you found.")
    elif action_type == "add":
        constraints.append("⚠️ ADD TASK: You MUST create or add new code. Use write_file or apply_patch.")
        constraints.append("Focus ONLY on adding the specific feature mentioned in the task description.")
    elif action_type == "edit":
        constraints.append("⚠️ EDIT TASK: You MUST modify existing code. Use apply_patch or write_file.")
        constraints.append("Edit ONLY the specific files/sections mentioned in the task description.")
    elif action_type == "test":
        constraints.append("⚠️ TEST TASK: You MUST run tests. Use run_tests or run_cmd.")
        constraints.append("Expected output: Test results showing pass/fail status.")
    elif action_type == "doc":
        constraints.append("⚠️ DOC TASK: You MUST update documentation files only.")
        constraints.append("Focus ONLY on documentation changes mentioned in the task description.")

    # General constraints for all tasks
    constraints.append("\n🎯 TASK BOUNDARIES:")
    constraints.append("- Complete ONLY this specific task, nothing more")
    constraints.append("- Do NOT work on other tasks from the plan")
    constraints.append("- Do NOT explore unrelated files")
    constraints.append("- If you already read a file in THIS task, do NOT read it again")
    constraints.append("- Maximum 3 file reads per task - use them wisely")
    constraints.append("- After exploration, make your changes immediately")

    return "\n".join(constraints)


def _build_execution_system_context(sys_info: Dict[str, Any], coding_mode: bool = False) -> str:
    """Build the system context string for execution, optionally with coding suffix.

    Args:
        sys_info: System information dictionary
        coding_mode: Whether to include coding-specific instructions

    Returns:
        Formatted system context string
    """
    base = EXECUTION_SYSTEM
    if coding_mode:
        base += CODING_EXECUTION_SUFFIX

    return f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{base}"""


def _summarize_old_messages(messages: List[Dict], tracker: 'SessionTracker' = None) -> str:
    """Summarize completed tasks from old messages.

    Args:
        messages: List of old message dicts to summarize
        tracker: Optional SessionTracker for enhanced summary

    Returns:
        Concise summary string of completed work
    """
    # Use enhanced summary if tracker available
    if tracker:
        return create_message_summary_from_history(messages, tracker)

    # Fallback: basic message-based summarization
    tasks_completed = []
    tools_used = []

    for msg in messages:
        # Extract task descriptions from user messages
        if msg.get("role") == "user" and "Task:" in msg.get("content", ""):
            content = msg["content"]
            if "Task:" in content:
                task_line = content.split("Task:", 1)[1].split("\n")[0].strip()
                if task_line and task_line not in tasks_completed:
                    tasks_completed.append(task_line)

        # Extract tool usage from tool messages
        if msg.get("role") == "tool":
            tool_name = msg.get("name", "unknown")
            if tool_name not in tools_used:
                tools_used.append(tool_name)

    # Build concise summary
    summary_parts = []
    if tasks_completed:
        # Limit to first 10 tasks
        task_list = tasks_completed[:10]
        summary_parts.append(f"Completed {len(tasks_completed)} tasks:")
        summary_parts.extend([f"  • {t[:80]}" for t in task_list])
        if len(tasks_completed) > 10:
            summary_parts.append(f"  ... and {len(tasks_completed) - 10} more")

    if tools_used:
        summary_parts.append(f"\nTools used: {', '.join(tools_used[:15])}")

    return "\n".join(summary_parts) if summary_parts else "Previous work completed successfully."


def _manage_message_history(messages: List[Dict], max_recent: Optional[int] = None, tracker: 'SessionTracker' = None) -> List[Dict]:
    """Keep recent messages and summarize old ones to prevent unbounded growth.

    This optimization prevents token explosion in long-running sessions by:
    1. Keeping the system message
    2. Summarizing old messages (tasks completed, tools used)
    3. Keeping the most recent N messages for context

    Args:
        messages: Current message history
        max_recent: Number of recent messages to keep (default: from config.CONTEXT_WINDOW_HISTORY)
        tracker: Optional SessionTracker for enhanced summaries

    Returns:
        Trimmed message list with summary of old messages
    """
    if max_recent is None:
        max_recent = config.CONTEXT_WINDOW_HISTORY
    if len(messages) <= max_recent + 1:  # +1 for system message
        return messages

    # Separate system message, old messages, and recent messages
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    start_idx = 1 if system_msg else 0

    # Keep last max_recent messages as-is
    recent_messages = messages[-max_recent:]

    # Messages to summarize (everything except system and recent)
    old_messages = messages[start_idx:-max_recent]

    if len(old_messages) > 0:
        # Create summary of completed work (use tracker if available)
        summary = _summarize_old_messages(old_messages, tracker)
        summary_msg = {
            "role": "user",
            "content": f"[Summary of previous work]\n{summary}\n\n[Continuing with recent context...]"
        }

        # Rebuild: system + summary + recent messages
        if system_msg:
            return [system_msg, summary_msg] + recent_messages
        else:
            return [summary_msg] + recent_messages

    return messages


def _trim_history_with_notice(
    messages: List[Dict], max_recent: Optional[int] = None, tracker: 'SessionTracker' = None
) -> Tuple[List[Dict], bool]:
    """Trim and summarize history while warning the user when context is reduced.

    Args:
        messages: Current message history
        max_recent: Number of recent messages to keep verbatim
        tracker: Optional SessionTracker for enhanced summaries

    Returns:
        A tuple of (trimmed messages, whether trimming occurred)
    """
    if max_recent is None:
        max_recent = config.CONTEXT_WINDOW_HISTORY

    if len(messages) <= max_recent + 1:  # +1 for optional system prompt
        return messages, False

    before_count = len(messages)
    trimmed = _manage_message_history(messages, max_recent=max_recent, tracker=tracker)
    after_count = len(trimmed)

    print(
        "  ℹ️  Context window trimmed: "
        f"{before_count} → {after_count} messages (keeping last {max_recent} + summary to avoid token overflow)"
    )

    return trimmed, True


def execution_mode(
    plan: ExecutionPlan,
    approved: bool = False,
    auto_approve: bool = True,
    tools: list = None,
    enable_action_review: bool = False,
    coding_mode: bool = False,
    state_manager: Optional[StateManager] = None,
    budget: Optional["ResourceBudget"] = None,
) -> bool:
    """Execute all tasks in the plan iteratively.

    This function executes tasks sequentially, maintaining a conversation with
    the LLM for context and handling tool invocations. It supports safety checks
    for destructive operations.

    Args:
        plan: ExecutionPlan with tasks to execute
        approved: Legacy parameter (ignored, kept for compatibility)
        auto_approve: If True (default), runs autonomously without initial approval.
                      Scary operations still require confirmation regardless.
        tools: List of available tools for LLM function calling (optional)
        enable_action_review: If True, review each action before execution (default: False)
        coding_mode: If True, use coding-specific execution prompts with test enforcement

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("EXECUTION MODE")
    print("=" * 60)

    # No upfront approval needed - runs autonomously
    # Scary operations will still prompt individually
    if not auto_approve:
        print("\nThis will execute all tasks with full autonomy.")
        print("⚠️  Note: Destructive operations will still require confirmation.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting autonomous execution...\n")
    if auto_approve:
        print("  ℹ️  Running in autonomous mode. Destructive operations will prompt for confirmation.\n")

    # Get system info and build context
    sys_info = get_system_info_cached()
    system_context = _build_execution_system_context(sys_info, coding_mode)
    model_name = config.EXECUTION_MODEL
    model_supports_tools = config.EXECUTION_SUPPORTS_TOOLS

    messages = [{"role": "system", "content": system_context}]
    message_queue = None
    cleanup_streaming_input = lambda: None
    redisplay_prompt = lambda: None
    try:
        from rev.execution.streaming import UserMessageQueue, MessagePriority
        from rev.terminal.input import start_streaming_input, stop_streaming_input, get_streaming_handler
        from rev.terminal.formatting import colorize, Colors

        message_queue = UserMessageQueue()
        input_handler = None

        def handle_user_input(text: str):
            if text.startswith("/stop") or text.startswith("/cancel"):
                message_queue.submit("STOP the current task immediately.", MessagePriority.INTERRUPT)
                print("\n  ?? [Interrupt requested]")
            elif text.startswith("/priority "):
                msg = text[len("/priority "):].strip()
                if msg:
                    message_queue.submit(msg, MessagePriority.HIGH)
                    print("\n  ?? [High priority message queued]")
            else:
                message_queue.submit(text, MessagePriority.NORMAL)
                print("\n  ?? [Guidance queued]")
            redisplay_prompt()

        input_prompt = f"{colorize('rev', Colors.BRIGHT_MAGENTA)}{colorize('>', Colors.BRIGHT_BLACK)} "
        input_handler = start_streaming_input(on_message=handle_user_input, prompt=input_prompt)

        def redisplay_prompt():
            handler = input_handler or get_streaming_handler()
            if handler:
                handler.redisplay_prompt()

        def cleanup_streaming_input():
            stop_streaming_input()
    except Exception as e:
        print(f"  ?? Interactive input disabled: {e}")
        message_queue = None
    max_iterations = MAX_EXECUTION_ITERATIONS
    iteration = 0

    # Initialize session tracker for comprehensive summarization
    session_tracker = SessionTracker()
    print(f"  📊 Session tracking enabled (ID: {session_tracker.session_id})\n")
    exec_context = ExecutionContext(plan)
    tool_limits = {
        "read_file": MAX_READ_FILE_PER_TASK,
        "search_code": MAX_SEARCH_CODE_PER_TASK,
        "run_cmd": MAX_RUN_CMD_PER_TASK,
    }
    budget_warned_tasks = set()

    while not plan.is_complete() and iteration < max_iterations:
        # Check for escape key interrupt
        if get_escape_interrupt():
            print("\n⚠️  Execution interrupted by ESC key")
            set_escape_interrupt(False)

            # Mark current task as stopped
            current_task = plan.get_current_task()
            if current_task:
                plan.mark_task_stopped(current_task)

            if state_manager:
                state_manager.on_interrupt(current_task)
            else:
                # Save checkpoint for resume
                try:
                    checkpoint_path = plan.save_checkpoint()
                    print(f"✓ Checkpoint saved to: {checkpoint_path}")
                    print(f"  Use 'rev resume {checkpoint_path}' to continue")
                except Exception as e:
                    print(f"✗ Failed to save checkpoint: {e}")

            return False

        iteration += 1
        current_task = plan.get_current_task()

        budget_warned = False
        if budget:
            budget.update_time()
            if budget.is_exceeded():
                print(f"⚠️ Resource budget exceeded before starting task loop: {budget.get_usage_summary()} (continuing)")
                budget_warned = True

        print(f"\n[Task {plan.current_index + 1}/{len(plan.tasks)}] {current_task.description}")
        print(f"[Type: {current_task.action_type}]")
        redisplay_prompt()

        current_task.status = TaskStatus.IN_PROGRESS
        if state_manager:
            state_manager.on_task_started(current_task)

        # Reset per-task deduplication tracking
        exec_context.reset_for_new_task()

        # Log task start
        debug_logger = get_logger()
        debug_logger.log_task_status(
            current_task.task_id,
            "IN_PROGRESS",
            {
                "task_index": plan.current_index + 1,
                "total_tasks": len(plan.tasks),
                "description": current_task.description,
                "action_type": current_task.action_type
            }
        )

        # Track task start
        session_tracker.track_task_started(current_task.description)

        # Get session context (learnings from previous tasks in this run)
        session_context = exec_context.get_session_context()

        # Build task-specific constraints
        task_constraints = _build_task_constraints(current_task)

        # Add task to conversation with session context and constraints
        task_prompt = f"""Task: {current_task.description}
Action type: {current_task.action_type}

{task_constraints}
"""
        if session_context:
            task_prompt += f"""
SESSION CONTEXT (from previous tasks in this run):
{session_context}

IMPORTANT: Do not repeat failed commands or search unavailable paths listed above.
"""
        task_prompt += "\nExecute this task completely. When done, respond with TASK_COMPLETE."

        messages.append({
            "role": "user",
            "content": task_prompt
        })

        # Execute task with tool calls
        task_iterations = 0
        base_task_iterations = MAX_TASK_ITERATIONS
        warn_task_iterations = max(1, int(base_task_iterations * 0.8))
        max_task_iterations = base_task_iterations
        task_complete = False
        tool_usage = {name: 0 for name in tool_limits}
        over_budget_hits = {name: 0 for name in tool_limits}
        prompt_tokens_used = 0
        tools_enabled = model_supports_tools
        no_tool_call_streak = 0
        iter_warned = False

        while task_iterations < max_task_iterations and not task_complete:
            # Check for escape key interrupt during task execution
            if get_escape_interrupt():
                print("\n⚠️  Task execution interrupted by ESC key")
                set_escape_interrupt(False)

                # Mark current task as stopped
                plan.mark_task_stopped(current_task)

                if state_manager:
                    state_manager.on_interrupt(current_task)
                else:
                    # Save checkpoint for resume
                    try:
                        checkpoint_path = plan.save_checkpoint()
                        print(f"✓ Checkpoint saved to: {checkpoint_path}")
                        print(f"  Use 'rev resume {checkpoint_path}' to continue")
                    except Exception as e:
                        print(f"✗ Failed to save checkpoint: {e}")

                cleanup_streaming_input()
                return False

            if message_queue and message_queue.has_pending():
                pending = message_queue.get_pending()
                for user_msg in pending:
                    messages.append(user_msg.to_llm_message())
                    print("\n  💬 Injected user guidance into conversation")
                    redisplay_prompt()
                    if "STOP" in user_msg.content.upper():
                        print("\n⏹️  Stop requested by user")
                        plan.mark_task_stopped(current_task)
                        cleanup_streaming_input()
                        return False

            task_iterations += 1
            if task_iterations >= warn_task_iterations and not iter_warned:
                print(f"⚠️ Task {plan.current_index + 1} nearing iteration limit ({task_iterations}/{max_task_iterations})")
                iter_warned = True

            call_tools = tools if tools_enabled and model_supports_tools else None
            llm_messages = _prepare_llm_messages(messages, exec_context, session_tracker)
            response = ollama_chat(llm_messages, tools=call_tools, model=model_name, supports_tools=model_supports_tools)

            if "error" in response:
                error_msg = response['error']
                print(f"  ✗ Error: {error_msg}")

                # If we keep getting errors, try without tools
                if "400" in error_msg:
                    tools_enabled = False
                    if messages and messages[0].get("role") == "system" and "Tool calling is disabled" not in messages[0].get("content", ""):
                        messages[0]["content"] = messages[0]["content"] + "\n\nTool calling is disabled; provide explicit file edits & patches."
                    messages.append({
                        "role": "user",
                        "content": "Tool calling is disabled due to previous errors. Provide explicit file edits and unified diffs."
                    })
                    print("  → Disabling tools for this task and retrying without tool support...")
                    response = ollama_chat(llm_messages, tools=None, model=model_name, supports_tools=False)

                if "error" in response:
                    plan.mark_failed(error_msg)
                    if state_manager:
                        state_manager.on_task_failed(current_task)
                    break

            if "usage" in response:
                usage = response.get("usage", {}) or {}
                prompt_tokens_used += usage.get("prompt", 0) or 0
                if budget:
                    budget.update_tokens(usage.get("total", 0) or 0)
                    budget.update_time()
                    if budget.is_exceeded() and not budget_warned:
                        print(f"  ⚠️ Resource budget exceeded during execution: {budget.get_usage_summary()} (continuing)")
                        budget_warned = True

            msg = response.get("message", {})
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            # Allow ESC to interrupt after LLM response but before any tool execution
            if get_escape_interrupt():
                print("\n⚠️  Task execution interrupted by ESC key")
                set_escape_interrupt(False)
                plan.mark_task_stopped(current_task)
                if state_manager:
                    state_manager.on_interrupt(current_task)
                task_complete = True
                _log_usage(False)
                break

            # Add assistant response to conversation
            messages.append(msg)

            # Execute tool calls FIRST before checking completion
            if tool_calls:
                for tool_call in tool_calls:
                    # Check for escape key interrupt before each tool execution
                    if get_escape_interrupt():
                        print("\n⚠️  Tool execution interrupted by ESC key")
                        set_escape_interrupt(False)

                        # Mark current task as stopped
                        plan.mark_task_stopped(current_task)
                        if state_manager:
                            state_manager.on_interrupt(current_task)

                        # Save checkpoint for resume
                        try:
                            checkpoint_path = plan.save_checkpoint()
                            print(f"✓ Checkpoint saved to: {checkpoint_path}")
                            print(f"  Use 'rev resume {checkpoint_path}' to continue")
                        except Exception as e:
                            print(f"✗ Failed to save checkpoint: {e}")

                        task_complete = True
                        break

                    func = tool_call.get("function", {})
                    tool_name = func.get("name")
                    tool_args = func.get("arguments", {})

                    if isinstance(tool_args, str):
                        try:
                            tool_args = json.loads(tool_args)
                        except:
                            tool_args = {}

                    """
                    # Check for back-to-back duplicate tool call (exact same args)
                    if exec_context.is_duplicate_call(tool_name, tool_args):
                        print(f"  ⚠️ Skipping duplicate {tool_name} call (same args back-to-back)")
                        messages.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": f"DUPLICATE_CALL: This exact {tool_name} call was just executed. Avoid calling the same tool with identical arguments twice in a row."
                        })
                        continue
                    
                    
                    # Check for loop pattern (same tool called repeatedly)
                    loop_warning = exec_context.detect_loop_pattern()
                    if loop_warning:
                        print(f"  ⚠️ {loop_warning}")
                        messages.append({
                            "role": "user",
                            "content": f"WARNING: {loop_warning}. Stop exploring and make a concrete edit using write_file or apply_patch NOW."
                        })
                    """

                    # Prevent review tasks from performing edits
                    edit_tools = {"write_file", "apply_patch"}
                    if current_task.action_type == "review" and tool_name in edit_tools:
                        print(f"  ?? Blocking {tool_name} during review task")
                        messages.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": f"BLOCKED: Review tasks must not modify files. Complete the review for '{current_task.description}' and move to the next task."
                        })
                        continue

                    """
                    # Check if exploration should be blocked for edit/add tasks
                    exploration_tools = {"read_file", "search_code", "list_dir", "tree_view", "get_repo_context"}
                    if tool_name in exploration_tools and exec_context.should_block_exploration(current_task.action_type):
                        print(f"  🚫 Blocking {tool_name} - exploration disabled for this task, make an edit now")
                        messages.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": f"BLOCKED: Exploration is disabled. You MUST use write_file or apply_patch to make changes now. The task is '{current_task.description}'. Create the implementation with your current knowledge."
                        })
                        continue
                    """


                    # Check if too much exploration without editing (threshold lowered for faster intervention)
                    if current_task.action_type in {"add", "edit"} and exec_context.is_exploration_heavy(threshold=5):
                        warning_count = exec_context.increment_force_edit_warning(current_task.action_type)
                        if warning_count == 1:
                            print(f"  ⚠️ Exploration budget exhausted - forcing edit mode (warning 1/2)")
                            messages.append({
                                "role": "user",
                                "content": f"You have done extensive exploration without making any edits. STOP searching/reading and create the code change NOW using write_file or apply_patch. The task is: '{current_task.description}'. Create the best-effort implementation immediately."
                            })
                            exec_context.exploration_count = 3  # Partial reset - triggers warning 2 faster
                        else:
                            print(f"  🛑 Exploration blocked - you MUST make an edit now")
                            messages.append({
                                "role": "user",
                                "content": f"FINAL WARNING: Exploration is now DISABLED for this task. You MUST use write_file or apply_patch immediately. The task is: '{current_task.description}'. Based on what you've learned, create the code NOW. Do not request any more file reads or searches."
                            })
                            # Don't reset - blocking will take over on next exploration attempt

                    # Record this tool call for deduplication tracking
                    exec_context.record_tool_call(tool_name, tool_args)

                    # Final escape check immediately before executing the tool
                    if get_escape_interrupt():
                        print("\n⚠️  Tool execution interrupted by ESC key")
                        set_escape_interrupt(False)
                        plan.mark_task_stopped(current_task)
                        if state_manager:
                            state_manager.on_interrupt(current_task)
                        task_complete = True
                        break

                    # Enforce per-task tool budgets
                    allowed, budget_msg = _consume_tool_budget(tool_name, tool_usage, tool_limits)
                    if not allowed:
                        over_budget_hits[tool_name] = over_budget_hits.get(tool_name, 0) + 1
                        debug_logger.log("executor", "TOOL_BUDGET_EXCEEDED", {
                            "tool": tool_name,
                            "count": over_budget_hits[tool_name],
                        }, "WARNING")
                        if over_budget_hits[tool_name] == 1:
                            limit = tool_limits.get(tool_name)
                            used = tool_usage.get(tool_name, 0)
                            print(f"  ⚠️ {tool_name} budget reached for this task ({used}/{limit}); please continue without additional {tool_name} calls.")
                        messages.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": budget_msg
                        })
                        messages.append({
                            "role": "user",
                            "content": f"You have reached the {tool_name} call limit for this task. Provide next steps without more {tool_name} calls."
                        })
                        continue

                    # Check if this is a scary operation
                    is_scary, scary_reason = is_scary_operation(
                        tool_name,
                        tool_args,
                        current_task.action_type
                    )

                    if is_scary:
                        operation_desc = format_operation_description(tool_name, tool_args)
                        if not prompt_scary_operation(operation_desc, scary_reason):
                            print(f"  ✗ Operation cancelled by user")
                            plan.mark_failed("User cancelled destructive operation")
                            if state_manager:
                                state_manager.on_task_failed(current_task)
                            task_complete = True
                            break

                    # Action review (if enabled)
                    action_review = None
                    if enable_action_review:
                        action_desc = f"{tool_name} with {len(tool_args)} arguments"
                        action_review = review_action(
                            action_type=current_task.action_type,
                            action_description=action_desc,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            context=current_task.description
                        )

                        if not action_review.approved:
                            display_action_review(action_review, action_desc)
                            print(f"  ✗ Action blocked by review agent")

                            # Inject feedback into conversation so LLM can adjust
                            feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                            if feedback:
                                messages.append({
                                    "role": "user",
                                    "content": feedback
                                })

                            # Don't fail immediately - let LLM try a different approach
                            continue
                        elif action_review.security_warnings or action_review.concerns:
                            display_action_review(action_review, action_desc)

                    # Serve from cache when possible
                    if tool_name == "read_file":
                        path = tool_args.get("path")
                        cached_content = exec_context.get_code(path)
                        if cached_content is not None:
                            result = cached_content
                        else:
                            result = execute_tool(tool_name, tool_args)
                            if not _has_error_result(result):
                                exec_context.set_code(path, result)
                                exec_context.add_snippet(path, 1, None, result)
                    elif tool_name == "search_code":
                        cached_search = exec_context.get_search(_make_search_cache_key(tool_args))
                        if cached_search is not None:
                            result = cached_search
                        else:
                            result = execute_tool(tool_name, tool_args)
                            if not _has_error_result(result):
                                exec_context.set_search(_make_search_cache_key(tool_args), result)

                        if not _has_error_result(result):
                            result = _augment_search_results(
                                result,
                                tool_args,
                                exec_context,
                                tool_limits,
                                tool_usage,
                                session_tracker,
                                debug_logger,
                            )
                    elif tool_name == "write_file":
                        path = tool_args.get("path")
                        result = execute_tool(tool_name, tool_args)
                        if not _has_error_result(result):
                            exec_context.invalidate_code(path)
                            exec_context.set_code(path, tool_args.get("content", ""))
                    elif tool_name == "apply_patch":
                        result = execute_tool(tool_name, tool_args)
                        if not _has_error_result(result):
                            exec_context.clear_code_cache()
                    else:
                        result = execute_tool(tool_name, tool_args)

                    # Track tool usage
                    session_tracker.track_tool_call(tool_name, tool_args)

                    # Inject review feedback into conversation (if any concerns/warnings)
                    if enable_action_review and action_review:
                        feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                        if feedback:
                            messages.append({
                                "role": "user",
                                "content": feedback
                            })

                    # Add tool result to conversation
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": result
                    })
                    redisplay_prompt()

                    # Track failures in session context (persists across tasks)
                    if _has_error_result(result):
                        try:
                            error_data = json.loads(result)
                            error_msg = error_data.get("error", "Unknown error")
                            if tool_name == "run_cmd":
                                cmd = tool_args.get("cmd", "")[:80]
                                exec_context.record_failed_command(cmd, error_msg)
                            elif tool_name in {"read_file", "search_code", "list_dir"}:
                                path = tool_args.get("path", tool_args.get("include", ""))
                                if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                                    exec_context.record_unavailable_path(path)
                        except:
                            pass

                    # Check for test failures and track results
                    if tool_name == "run_tests":
                        session_tracker.track_test_results(result)
                        try:
                            result_data = json.loads(result)
                            rc = result_data.get("rc", 0)
                            if rc != 0:
                                print(f"  ⚠ Tests failed (rc={rc})")
                                redisplay_prompt()
                                # NEW: Inject explicit feedback for the LLM in coding mode
                                if coding_mode:
                                    messages.append({
                                        "role": "user",
                                        "content": (
                                            f"Tests failed with exit code {rc}. "
                                            f"Here is the test output:\n\n{result}\n\n"
                                            "You MUST fix the underlying issues and re-run tests "
                                            "before responding with TASK_COMPLETE."
                                        ),
                                    })
                        except:
                            pass

            # Check if task is complete AFTER executing tool calls
            if "TASK_COMPLETE" in content or "task complete" in content.lower():
                print(f"  ✓ Task completed")
                redisplay_prompt()
                plan.mark_completed(content)
                if state_manager:
                    state_manager.on_task_completed(current_task)
                session_tracker.track_task_completed(current_task.description)
                task_complete = True
                break

            # If model responds but doesn't use tools and doesn't complete task
            if not tool_calls and content:
                # Model is thinking/responding without tool calls
                print(f"  → {content[:200]}")
                no_tool_call_streak += 1
                applied_fallback = _apply_text_fallbacks(
                    content,
                    current_task.action_type,
                    messages,
                    session_tracker,
                    exec_context,
                    debug_logger,
                )
                if applied_fallback:
                    continue

                # If model keeps responding without tools or completion, inject guidance instead of failing
                if no_tool_call_streak >= 3:
                    print(f"  ⚠️ Model still not calling tools; injecting reminder and continuing.")
                    reminder = (
                        "You must call the available tools (read_file, search_code, write_file, "
                        "apply_patch, run_cmd, run_tests) to inspect and modify the code. "
                        "Do not respond with analysis only."
                    )
                    messages.append({"role": "user", "content": reminder})
                    no_tool_call_streak = 0
                    continue
            else:
                no_tool_call_streak = 0

        if not task_complete and task_iterations >= max_task_iterations:
            error_msg = "Exceeded iteration limit"
            print(f"  ⚠️ Task exceeded iteration limit ({task_iterations}/{max_task_iterations}) (marking stopped)")
            plan.mark_task_stopped(current_task)
            current_task.error = error_msg
            if state_manager:
                try:
                    state_manager.on_task_stopped(current_task)  # type: ignore[attr-defined]
                except Exception:
                    pass

        debug_logger.log("executor", "TASK_USAGE", {
            "task_id": current_task.task_id,
            "description": current_task.description,
            "read_file_calls": tool_usage.get("read_file", 0),
            "search_code_calls": tool_usage.get("search_code", 0),
            "run_cmd_calls": tool_usage.get("run_cmd", 0),
            "prompt_tokens": prompt_tokens_used,
        }, "INFO")

        # OPTIMIZATION: Manage message history to prevent unbounded growth
        messages, _ = _trim_history_with_notice(messages, max_recent=CONTEXT_WINDOW_HISTORY, tracker=session_tracker)

    if not plan.is_complete() and iteration >= max_iterations:
        error_msg = "Exceeded execution iteration limit"
        print(f"\n✗ Execution exceeded iteration limit ({max_iterations}); stopping.")
        plan.mark_failed(error_msg)
        session_tracker.track_task_failed("execution_loop", error_msg)

    # Final summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())
    print()

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○",
            TaskStatus.STOPPED: "⏸"
        }.get(task.status, "?")

        print(f"{status_icon} {i}. {task.description} [{task.status.value}]")
        if task.error:
            print(f"    Error: {task.error}")

    print("=" * 60)

    # Finalize and display session summary
    session_tracker.finalize()
    print("\n" + "=" * 60)
    print("SESSION SUMMARY")
    print("=" * 60)
    print(session_tracker.get_summary(detailed=False))
    print("=" * 60)

    # Save session summary to disk
    try:
        summary_path = session_tracker.save_to_file()
        print(f"\n📊 Session summary saved to: {summary_path}")

        # Emit metrics for evaluation and monitoring
        metrics_path = session_tracker.emit_metrics()
        print(f"📈 Metrics emitted to: {metrics_path}")
    except Exception as e:
        print(f"\n⚠️  Failed to save session data: {e}")

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)


def execute_single_task(
    task: Task,
    plan: ExecutionPlan,
    sys_info: Dict[str, Any],
    auto_approve: bool = True,
    tools: list = None,
    enable_action_review: bool = False,
    coding_mode: bool = False,
    state_manager: Optional[StateManager] = None,
    exec_context: Optional[ExecutionContext] = None,
    tool_limits: Optional[Dict[str, int]] = None,
    budget: Optional["ResourceBudget"] = None,
) -> bool:
    """Execute a single task (for concurrent execution).

    This function is designed to be run in a thread pool and executes a single
    task independently with proper tool invocation and error handling.

    Args:
        task: The task to execute
        plan: The ExecutionPlan containing all tasks
        sys_info: System information for context
        auto_approve: If True, skip initial approval prompt
        tools: List of available tools for LLM function calling (optional)
        enable_action_review: If True, review each action before execution (default: False)
        coding_mode: If True, use coding-specific execution prompts

    Returns:
        True if task completed successfully, False otherwise
    """
    print(f"\n[Task {task.task_id + 1}/{len(plan.tasks)}] {task.description}")
    print(f"[Type: {task.action_type}]")

    plan.mark_task_in_progress(task)
    if state_manager:
        state_manager.on_task_started(task)

    model_name = config.EXECUTION_MODEL
    model_supports_tools = config.EXECUTION_SUPPORTS_TOOLS

    exec_context = exec_context or ExecutionContext(plan)
    # Reset per-task deduplication tracking
    exec_context.reset_for_new_task()
    tool_limits = tool_limits or {
        "read_file": MAX_READ_FILE_PER_TASK,
        "search_code": MAX_SEARCH_CODE_PER_TASK,
        "run_cmd": MAX_RUN_CMD_PER_TASK,
    }
    debug_logger = get_logger()

    system_context = _build_execution_system_context(sys_info, coding_mode)

    messages = [{"role": "system", "content": system_context}]

    # Add task to conversation with constraints
    task_constraints = _build_task_constraints(task)
    messages.append({
        "role": "user",
        "content": f"""Task: {task.description}
Action type: {task.action_type}

{task_constraints}

Execute this task completely. When done, respond with TASK_COMPLETE."""
    })

    # Execute task with tool calls
    task_iterations = 0
    base_task_iterations = MAX_TASK_ITERATIONS
    warn_task_iterations = max(1, int(base_task_iterations * 0.8))
    max_task_iterations = base_task_iterations
    task_complete = False
    tool_usage = {name: 0 for name in tool_limits}
    over_budget_hits = {name: 0 for name in tool_limits}
    prompt_tokens_used = 0
    tools_enabled = model_supports_tools
    no_tool_call_streak = 0
    budget_warned = False
    iter_warned = False

    def _log_usage(success: bool):
        debug_logger.log("executor", "TASK_USAGE", {
            "task_id": task.task_id,
            "description": task.description,
            "read_file_calls": tool_usage.get("read_file", 0),
            "search_code_calls": tool_usage.get("search_code", 0),
            "run_cmd_calls": tool_usage.get("run_cmd", 0),
            "prompt_tokens": prompt_tokens_used,
            "success": success,
        }, "INFO")

    while task_iterations < max_task_iterations and not task_complete:
        # Allow ESC to interrupt concurrent task execution immediately
        if get_escape_interrupt():
            print("\n⚠️  Task execution interrupted by ESC key")
            set_escape_interrupt(False)
            plan.mark_task_stopped(task)
            if state_manager:
                state_manager.on_interrupt(task)
            _log_usage(False)
            return False

        task_iterations += 1
        if task_iterations >= warn_task_iterations and not iter_warned:
            print(f"⚠️ Task {task.task_id + 1} nearing iteration limit ({task_iterations}/{max_task_iterations})")
            iter_warned = True

        if budget:
            budget.update_time()
            if budget.is_exceeded():
                if not budget_warned:
                    print(f"⚠️ Resource budget exceeded for task {task.task_id + 1}: {budget.get_usage_summary()} (continuing)")
                    budget_warned = True

        call_tools = tools if tools_enabled and model_supports_tools else None
        llm_messages = _prepare_llm_messages(messages, exec_context)
        response = ollama_chat(llm_messages, tools=call_tools, model=model_name, supports_tools=model_supports_tools)

        if "error" in response:
            error_msg = response['error']
            print(f"  ✗ Error: {error_msg}")

            if "400" in error_msg:
                tools_enabled = False
                if messages and messages[0].get("role") == "system" and "Tool calling is disabled" not in messages[0].get("content", ""):
                    messages[0]["content"] = messages[0]["content"] + "\n\nTool calling is disabled; provide explicit file edits & patches."
                messages.append({
                    "role": "user",
                    "content": "Tool calling is disabled due to previous errors. Provide explicit file edits and unified diffs."
                })
                print(f"  → Retrying without tool support...")
                response = ollama_chat(llm_messages, tools=None, model=model_name, supports_tools=False)

            if "error" in response:
                plan.mark_task_failed(task, error_msg)
                if state_manager:
                    state_manager.on_task_failed(task)
                _log_usage(False)
                return False

        if "usage" in response:
            usage = response.get("usage", {}) or {}
            prompt_tokens_used += usage.get("prompt", 0) or 0
            if budget:
                budget.update_tokens(usage.get("total", 0) or 0)
                budget.update_time()
                if budget.is_exceeded() and not budget_warned:
                    print(f"⚠️ Resource budget exceeded during execution for task {task.task_id + 1}: {budget.get_usage_summary()} (continuing)")
                    budget_warned = True

        msg = response.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # Add assistant response to conversation
        messages.append(msg)

        # Execute tool calls FIRST before checking completion
        if tool_calls:
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name")
                tool_args = func.get("arguments", {})

                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}

                """
                # Check for back-to-back duplicate tool call (exact same args)
                if exec_context.is_duplicate_call(tool_name, tool_args):
                    print(f"  ⚠️ Skipping duplicate {tool_name} call (same args back-to-back)")
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": f"DUPLICATE_CALL: This exact {tool_name} call was just executed. Avoid calling the same tool with identical arguments twice in a row."
                    })
                    continue
                
                
                # Check for loop pattern (same tool called repeatedly)
                loop_warning = exec_context.detect_loop_pattern()
                if loop_warning:
                    print(f"  ⚠️ {loop_warning}")
                    messages.append({
                        "role": "user",
                        "content": f"WARNING: {loop_warning}. Stop exploring and make a concrete edit using write_file or apply_patch NOW."
                    })
                """

                # Prevent review tasks from performing edits
                edit_tools = {"write_file", "apply_patch"}
                if task.action_type == "review" and tool_name in edit_tools:
                    print(f"  ?? Blocking {tool_name} during review task")
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": f"BLOCKED: Review tasks must not modify files. Gather the context for '{task.description}' and let the next task handle edits."
                    })
                    continue

                """
                # Check if exploration should be blocked for edit/add tasks
                exploration_tools = {"read_file", "search_code", "list_dir", "tree_view", "get_repo_context"}
                if tool_name in exploration_tools and exec_context.should_block_exploration(task.action_type):
                    print(f"  🚫 Blocking {tool_name} - exploration disabled for this task, make an edit now")
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": f"BLOCKED: Exploration is disabled. You MUST use write_file or apply_patch to make changes now. The task is '{task.description}'. Create the implementation with your current knowledge."
                    })
                    continue
                """

                """
                # Check if too much exploration without editing (threshold lowered for faster intervention)
                if task.action_type in {"add", "edit"} and exec_context.is_exploration_heavy(threshold=5):
                    warning_count = exec_context.increment_force_edit_warning(task.action_type)
                    if warning_count == 1:
                        print(f"  ⚠️ Exploration budget exhausted - forcing edit mode (warning 1/2)")
                        messages.append({
                            "role": "user",
                            "content": f"You have done extensive exploration without making any edits. STOP searching/reading and create the code change NOW using write_file or apply_patch. The task is: '{task.description}'. Create the best-effort implementation immediately."
                        })
                        exec_context.exploration_count = 3  # Partial reset - triggers warning 2 faster
                    else:
                        print(f"  🛑 Exploration blocked - you MUST make an edit now")
                        messages.append({
                            "role": "user",
                            "content": f"FINAL WARNING: Exploration is now DISABLED for this task. You MUST use write_file or apply_patch immediately. The task is: '{task.description}'. Based on what you've learned, create the code NOW. Do not request any more file reads or searches."
                        })
                        # Don't reset - blocking will take over on next exploration attempt

                """

                # Record this tool call for deduplication tracking
                exec_context.record_tool_call(tool_name, tool_args)

                allowed, budget_msg = _consume_tool_budget(tool_name, tool_usage, tool_limits)
                if not allowed:
                    over_budget_hits[tool_name] = over_budget_hits.get(tool_name, 0) + 1
                    debug_logger.log("executor", "TOOL_BUDGET_EXCEEDED", {
                        "tool": tool_name,
                        "count": over_budget_hits[tool_name],
                        "task_id": task.task_id,
                    }, "WARNING")
                    if over_budget_hits[tool_name] == 1:
                        limit = tool_limits.get(tool_name)
                        used = tool_usage.get(tool_name, 0)
                        print(f"  ⚠️ {tool_name} budget reached for this task ({used}/{limit}); please continue without additional {tool_name} calls.")
                    messages.append({
                        "role": "tool",
                        "name": tool_name,
                        "content": budget_msg
                    })
                    messages.append({
                        "role": "user",
                        "content": f"You have reached the {tool_name} call limit for this task. Provide next steps without more {tool_name} calls."
                    })
                    continue

                # Check if this is a scary operation
                is_scary, scary_reason = is_scary_operation(
                    tool_name,
                    tool_args,
                    task.action_type
                )

                if is_scary:
                    operation_desc = format_operation_description(tool_name, tool_args)
                    if not prompt_scary_operation(operation_desc, scary_reason):
                        print(f"  ✗ Operation cancelled by user")
                        plan.mark_task_failed(task, "User cancelled destructive operation")
                        if state_manager:
                            state_manager.on_task_failed(task)
                        _log_usage(False)
                        return False

                # Action review (if enabled)
                action_review = None
                if enable_action_review:
                    action_desc = f"{tool_name} with {len(tool_args)} arguments"
                    action_review = review_action(
                        action_type=task.action_type,
                        action_description=action_desc,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        context=task.description
                    )

                    if not action_review.approved:
                        display_action_review(action_review, action_desc)
                        print(f"  ✗ Action blocked by review agent")

                        # Inject feedback into conversation so LLM can adjust
                        feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                        if feedback:
                            messages.append({
                                "role": "user",
                                "content": feedback
                            })

                        # Don't fail immediately - let LLM try a different approach
                        continue
                    elif action_review.security_warnings or action_review.concerns:
                        display_action_review(action_review, action_desc)

                if tool_name == "read_file":
                    path = tool_args.get("path")
                    cached_content = exec_context.get_code(path)
                    if cached_content is not None:
                        result = cached_content
                    else:
                        result = execute_tool(tool_name, tool_args)
                        if not _has_error_result(result):
                            exec_context.set_code(path, result)
                            exec_context.add_snippet(path, 1, None, result)
                elif tool_name == "search_code":
                    cache_key = _make_search_cache_key(tool_args)
                    cached_search = exec_context.get_search(cache_key)
                    if cached_search is not None:
                        result = cached_search
                    else:
                        result = execute_tool(tool_name, tool_args)
                        if not _has_error_result(result):
                            exec_context.set_search(cache_key, result)

                    if not _has_error_result(result):
                        result = _augment_search_results(
                            result,
                            tool_args,
                            exec_context,
                            tool_limits,
                            tool_usage,
                            None,
                            debug_logger,
                        )
                elif tool_name == "write_file":
                    path = tool_args.get("path")
                    result = execute_tool(tool_name, tool_args)
                    if not _has_error_result(result):
                        exec_context.invalidate_code(path)
                        exec_context.set_code(path, tool_args.get("content", ""))
                elif tool_name == "apply_patch":
                    result = execute_tool(tool_name, tool_args)
                    if not _has_error_result(result):
                        exec_context.clear_code_cache()
                else:
                    result = execute_tool(tool_name, tool_args)

                # Inject review feedback into conversation (if any concerns/warnings)
                if enable_action_review and action_review:
                    feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                    if feedback:
                        messages.append({
                            "role": "user",
                            "content": feedback
                        })

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": result
                })

                # Check for test failures
                if tool_name == "run_tests":
                    try:
                        result_data = json.loads(result)
                        if result_data.get("rc", 0) != 0:
                            print(f"  ⚠ Tests failed (rc={result_data['rc']})")
                    except:
                        pass

        # Check if task is complete AFTER executing tool calls
        if "TASK_COMPLETE" in content or "task complete" in content.lower():
            print(f"  ✓ Task completed")
            plan.mark_task_completed(task, content)
            if state_manager:
                state_manager.on_task_completed(task)
            _log_usage(True)
            return True

        # If model responds but doesn't use tools and doesn't complete task
        if not tool_calls and content:
            # Model is thinking/responding without tool calls
            print(f"  → {content[:200]}")
            no_tool_call_streak += 1
            applied_fallback = _apply_text_fallbacks(content, task.action_type, messages, None, exec_context, debug_logger)
            if applied_fallback:
                continue

            # If model keeps responding without tools or completion, inject guidance instead of failing
            if no_tool_call_streak >= 3:
                print(f"  ⚠️ Model still not calling tools; injecting reminder and continuing.")
                reminder = (
                    "You must call the available tools (read_file, search_code, write_file, "
                    "apply_patch, run_cmd, run_tests) to inspect and modify the code. "
                    "Do not respond with analysis only."
                )
                messages.append({"role": "user", "content": reminder})
                no_tool_call_streak = 0
                continue
        else:
            no_tool_call_streak = 0

    if not task_complete:
        print(f"  ⚠️ Task exceeded iteration limit ({task_iterations}/{max_task_iterations}) (marking stopped)")
        plan.mark_task_stopped(task)
        task.error = "Exceeded iteration limit"
        if state_manager:
            try:
                state_manager.on_task_stopped(task)  # type: ignore[attr-defined]
            except Exception:
                pass
        _log_usage(False)
        cleanup_streaming_input()
        return True

    cleanup_streaming_input()
    _log_usage(True)
    return True


def concurrent_execution_mode(
    plan: ExecutionPlan,
    max_workers: int = 2,
    auto_approve: bool = True,
    tools: list = None,
    enable_action_review: bool = False,
    coding_mode: bool = False,
    state_manager: Optional[StateManager] = None,
    budget: Optional["ResourceBudget"] = None,
) -> bool:
    """Sequential wrapper to comply with single-worker execution only."""

    if max_workers <= 0:
        raise ValueError(f"max_workers must be greater than 0, got {max_workers}")

    if max_workers != 1:
        print(f"\n⚠️ Parallel execution is disabled. Forcing sequential mode (requested {max_workers} workers).")

    return execution_mode(
        plan,
        auto_approve=auto_approve,
        tools=tools,
        enable_action_review=enable_action_review,
        coding_mode=coding_mode,
        state_manager=state_manager,
        budget=budget,
    )


def fix_validation_failures(
    validation_feedback: str,
    user_request: str,
    tools: list = None,
    enable_action_review: bool = False,
    max_fix_attempts: int = 5,
    coding_mode: bool = False
) -> bool:
    """Attempt to fix validation failures based on feedback.

    This creates a self-healing mechanism where the LLM sees validation failures
    and attempts to fix them automatically.

    Args:
        validation_feedback: Formatted validation feedback from validator
        user_request: Original user request for context
        tools: List of available tools for LLM function calling
        enable_action_review: Whether to review fix actions
        max_fix_attempts: Maximum number of fix attempts
        coding_mode: If True, use test-writer specialized prompt

    Returns:
        True if fixes were attempted successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("AUTO-FIX MODE - Addressing Validation Failures")
    print("=" * 60)

    # Get system info for context
    sys_info = get_system_info_cached()

    # Use specialized test-writer prompt in coding mode
    system_prompt = EXECUTION_SYSTEM
    if coding_mode:
        system_prompt = TEST_WRITER_SYSTEM + "\n\n" + CODING_EXECUTION_SUFFIX

    system_context = f"""System Information:
OS: {sys_info['os']} {sys_info['os_release']}
Platform: {sys_info['platform']}
Architecture: {sys_info['architecture']}
Shell Type: {sys_info['shell_type']}

{system_prompt}

IMPORTANT: You are in AUTO-FIX mode. Your task is to analyze validation failures
and create fixes for them. Be methodical and targeted - fix one issue at a time."""

    messages = [
        {"role": "system", "content": system_context},
        {"role": "user", "content": f"""Original task: {user_request}

{validation_feedback}

Please analyze these validation failures and fix them. Complete each fix and report TASK_COMPLETE when all issues are resolved."""}
    ]

    iteration = 0
    fixes_complete = False

    while iteration < max_fix_attempts and not fixes_complete:
        iteration += 1
        print(f"\n→ Fix attempt {iteration}/{max_fix_attempts}")

        # Get LLM response
        response = ollama_chat(messages, tools=tools)

        if "error" in response:
            print(f"  ✗ Error during fix: {response['error']}")
            return False

        msg = response.get("message", {})
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        # Add assistant response to conversation
        messages.append(msg)

        # Execute tool calls
        if tool_calls:
            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name")
                tool_args = func.get("arguments", {})

                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}

                print(f"  → {tool_name}...")

                # Action review if enabled
                if enable_action_review:
                    from rev.execution.reviewer import review_action, display_action_review, format_review_feedback_for_llm
                    action_desc = f"{tool_name} with {len(tool_args)} arguments"
                    action_review = review_action(
                        action_type="fix",
                        action_description=action_desc,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        context="Auto-fixing validation failures"
                    )

                    if not action_review.approved:
                        display_action_review(action_review, action_desc)
                        feedback = format_review_feedback_for_llm(action_review, action_desc, tool_name)
                        if feedback:
                            messages.append({"role": "user", "content": feedback})
                        continue

                # Execute the fix
                result = execute_tool(tool_name, tool_args)

                # Add result to conversation
                messages.append({
                    "role": "tool",
                    "content": result
                })

        # Check if fixes are complete
        if "TASK_COMPLETE" in content or "task complete" in content.lower():
            print(f"  ✓ Fixes completed")
            fixes_complete = True
            break

        # If no tool calls and no completion, provide guidance
        if not tool_calls:
            print(f"  → LLM response: {content[:200]}")

    if iteration >= max_fix_attempts:
        print(f"  ⚠️  Reached maximum fix attempts ({max_fix_attempts})")
        return False

    return fixes_complete


# =============================================================================
# Streaming Execution Mode - Real-time interaction like Claude Code
# =============================================================================

def streaming_execution_mode(
    plan: ExecutionPlan,
    approved: bool = False,
    auto_approve: bool = True,
    tools: list = None,
    enable_action_review: bool = False,
    coding_mode: bool = False,
    state_manager: Optional[StateManager] = None,
    budget: Optional["ResourceBudget"] = None,
    on_chunk: Optional[callable] = None,
    on_user_message: Optional[callable] = None,
) -> bool:
    """Execute all tasks with streaming LLM output and real-time user interaction.

    This provides a Claude Code-like experience where:
    - LLM responses stream to the terminal in real-time
    - Users can submit messages while tasks are running
    - User messages are injected into the conversation
    - The LLM adapts its approach based on user feedback

    Args:
        plan: ExecutionPlan with tasks to execute
        approved: Legacy parameter (ignored)
        auto_approve: If True (default), runs autonomously
        tools: List of available tools for LLM function calling
        enable_action_review: If True, review each action before execution
        coding_mode: If True, use coding-specific execution prompts
        state_manager: Optional state manager for persistence
        budget: Optional resource budget
        on_chunk: Callback for each streaming chunk (default: print)
        on_user_message: Callback when user message is received

    Returns:
        True if all tasks completed successfully, False otherwise
    """
    from rev.llm.client import ollama_chat_stream
    from rev.execution.streaming import (
        StreamingExecutionManager,
        UserMessageQueue,
        MessagePriority,
    )
    from rev.terminal.input import start_streaming_input, stop_streaming_input, get_streaming_handler
    from rev.terminal.formatting import colorize, Colors

    print("\n" + "=" * 60)
    print("STREAMING EXECUTION MODE")
    print("=" * 60)
    print("  ℹ️  Type messages while tasks run to guide the LLM")
    print("  ℹ️  Special commands: /stop, /priority <msg>")
    print("=" * 60)

    if not auto_approve:
        print("\nThis will execute all tasks with streaming output.")
        response = input("Start execution? [y/N]: ").strip().lower()
        if response not in ["y", "yes"]:
            print("Execution cancelled.")
            return False

    print("\n✓ Starting streaming execution...\n")

    # Initialize streaming infrastructure
    message_queue = UserMessageQueue()

    def default_chunk_handler(chunk: str):
        """Default handler that prints chunks and keeps the prompt visible."""
        print(chunk, end='', flush=True)
        handler = get_streaming_handler()
        if handler:
            handler.redisplay_prompt()

    chunk_handler = on_chunk or default_chunk_handler

    # Create streaming manager
    streaming_manager = StreamingExecutionManager(
        message_queue=message_queue,
        on_chunk=chunk_handler,
        on_user_message=on_user_message,
    )
    streaming_manager.start()

    # Start background input handler
    def handle_user_input(text: str):
        """Handle user input during streaming execution."""
        if text.startswith('/stop') or text.startswith('/cancel'):
            message_queue.submit("STOP the current task immediately.", MessagePriority.INTERRUPT)
            print(f"\n  📩 [Interrupt requested]")
        elif text.startswith('/priority '):
            msg = text[len('/priority '):].strip()
            if msg:
                message_queue.submit(msg, MessagePriority.HIGH)
                print(f"\n  📩 [High priority: {msg[:50]}...]")
        else:
            message_queue.submit(text, MessagePriority.NORMAL)
            print(f"\n  📩 [Guidance: {text[:50]}...]")

    # Create prompt with same styling as REPL
    input_prompt = f"{colorize('rev', Colors.BRIGHT_MAGENTA)}{colorize('>', Colors.BRIGHT_BLACK)} "
    start_streaming_input(on_message=handle_user_input, prompt=input_prompt)

    try:
        # Get system info and build context
        sys_info = get_system_info_cached()
        system_context = _build_execution_system_context(sys_info, coding_mode)
        model_name = config.EXECUTION_MODEL
        model_supports_tools = config.EXECUTION_SUPPORTS_TOOLS

        messages = [{"role": "system", "content": system_context}]
        max_iterations = MAX_EXECUTION_ITERATIONS
        iteration = 0

        # Initialize session tracker
        session_tracker = SessionTracker()
        exec_context = ExecutionContext(plan)
        tool_limits = {
            "read_file": MAX_READ_FILE_PER_TASK,
            "search_code": MAX_SEARCH_CODE_PER_TASK,
            "run_cmd": MAX_RUN_CMD_PER_TASK,
        }

        while not plan.is_complete() and iteration < max_iterations:
            # Check for escape/interrupt
            if get_escape_interrupt() or streaming_manager.is_interrupted():
                print("\n⚠️  Execution interrupted")
                set_escape_interrupt(False)
                current_task = plan.get_current_task()
                if current_task:
                    plan.mark_task_stopped(current_task)
                break

            iteration += 1
            current_task = plan.get_current_task()

            print(f"\n{'='*60}")
            print(f"[Task {plan.current_index + 1}/{len(plan.tasks)}] {current_task.description}")
            print(f"[Type: {current_task.action_type}]")
            print(f"{'='*60}\n")

            current_task.status = TaskStatus.IN_PROGRESS
            if state_manager:
                state_manager.on_task_started(current_task)

            exec_context.reset_for_new_task()

            # Build task prompt with constraints
            session_context = exec_context.get_session_context()
            task_constraints = _build_task_constraints(current_task)
            task_prompt = f"""Task: {current_task.description}
Action type: {current_task.action_type}

{task_constraints}
"""
            if session_context:
                task_prompt += f"\nSESSION CONTEXT:\n{session_context}\n"
            task_prompt += "\nExecute this task completely. When done, respond with TASK_COMPLETE."

            messages.append({"role": "user", "content": task_prompt})

            # Task execution loop
            task_iterations = 0
            max_task_iterations = MAX_TASK_ITERATIONS
            task_complete = False
            tool_usage = {name: 0 for name in tool_limits}
            tools_enabled = model_supports_tools

            while task_iterations < max_task_iterations and not task_complete:
                # Check for interrupt
                if get_escape_interrupt() or streaming_manager.is_interrupted():
                    print("\n⚠️  Task interrupted")
                    plan.mark_task_stopped(current_task)
                    task_complete = True
                    break

                task_iterations += 1

                # CHECK FOR USER MESSAGES - inject before LLM call
                if message_queue.has_pending():
                    pending = message_queue.get_pending()
                    for user_msg in pending:
                        llm_msg = user_msg.to_llm_message()
                        messages.append(llm_msg)
                        print(f"\n  💬 Injected user guidance into conversation")
                        handler = get_streaming_handler()
                        if handler:
                            handler.redisplay_prompt()

                        # Check for stop command
                        if "STOP" in user_msg.content.upper():
                            print("\n  🛑 Stop requested by user")
                            plan.mark_task_stopped(current_task)
                            task_complete = True
                            break

                if task_complete:
                    break

                # Make streaming LLM call
                print("\n  🤖 ", end='', flush=True)

                def check_interrupt():
                    return get_escape_interrupt() or streaming_manager.is_interrupted()

                def check_messages():
                    # Signal that messages are pending (will be injected next iteration)
                    if message_queue.has_pending():
                        print("\n  📥 [Message pending - will process after response]", end='', flush=True)

                call_tools = tools if tools_enabled and model_supports_tools else None
                llm_messages = _prepare_llm_messages(messages, exec_context, session_tracker)

                try:
                    response = ollama_chat_stream(
                        llm_messages,
                        tools=call_tools,
                        model=model_name,
                        supports_tools=model_supports_tools,
                        on_chunk=chunk_handler,
                        check_interrupt=check_interrupt,
                        check_user_messages=check_messages,
                    )
                except KeyboardInterrupt:
                    print("\n⚠️  Request cancelled")
                    plan.mark_task_stopped(current_task)
                    task_complete = True
                    break

                print()  # Newline after streaming output

                # Re-display prompt after LLM response
                handler = get_streaming_handler()
                if handler:
                    handler.redisplay_prompt()

                if "error" in response:
                    print(f"  ✗ Error: {response['error']}")
                    if "400" in str(response['error']):
                        tools_enabled = False
                        messages.append({
                            "role": "user",
                            "content": "Tool calling disabled. Provide explicit file edits."
                        })
                    continue

                msg = response.get("message", {})
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls", [])

                messages.append(msg)

                # Execute tool calls
                if tool_calls:
                    for tool_call in tool_calls:
                        if get_escape_interrupt() or streaming_manager.is_interrupted():
                            task_complete = True
                            break

                        func = tool_call.get("function", {})
                        tool_name = func.get("name")
                        tool_args = func.get("arguments", {})

                        if isinstance(tool_args, str):
                            try:
                                tool_args = json.loads(tool_args)
                            except:
                                tool_args = {}

                        """
                        # Check for back-to-back duplicate
                        if exec_context.is_duplicate_call(tool_name, tool_args):
                            print(f"  ⚠️ Skipping duplicate {tool_name} call (same args back-to-back)")
                            messages.append({
                                "role": "tool",
                                "name": tool_name,
                                "content": "DUPLICATE_CALL: This call was just executed in the previous step."
                            })
                            continue
                        """

                        # Prevent review tasks from performing edits
                        edit_tools = {"write_file", "apply_patch"}
                        if current_task.action_type == "review" and tool_name in edit_tools:
                            print(f"  ?? Blocking {tool_name} during review task")
                            messages.append({
                                "role": "tool",
                                "name": tool_name,
                                "content": f"BLOCKED: Review tasks must not modify files. Gather the context for '{current_task.description}' and let the next task handle edits."
                            })
                            continue

                        exec_context.record_tool_call(tool_name, tool_args)

                        # Check budget
                        allowed, budget_msg = _consume_tool_budget(tool_name, tool_usage, tool_limits)
                        if not allowed:
                            messages.append({
                                "role": "tool",
                                "name": tool_name,
                                "content": budget_msg
                            })
                            continue

                        # Check for scary operation
                        is_scary, scary_reason = is_scary_operation(
                            tool_name, tool_args, current_task.action_type
                        )
                        if is_scary:
                            operation_desc = format_operation_description(tool_name, tool_args)
                            if not prompt_scary_operation(operation_desc, scary_reason):
                                print(f"  ✗ Operation cancelled")
                                plan.mark_failed("User cancelled destructive operation")
                                task_complete = True
                                break

                        # Execute tool
                        print(f"  🔧 {tool_name}...", end='', flush=True)

                        if tool_name == "read_file":
                            path = tool_args.get("path")
                            cached = exec_context.get_code(path)
                            if cached is not None:
                                result = cached
                            else:
                                result = execute_tool(tool_name, tool_args)
                                if not _has_error_result(result):
                                    exec_context.set_code(path, result)
                        elif tool_name == "write_file":
                            path = tool_args.get("path")
                            result = execute_tool(tool_name, tool_args)
                            if not _has_error_result(result):
                                exec_context.invalidate_code(path)
                        elif tool_name == "apply_patch":
                            result = execute_tool(tool_name, tool_args)
                            if not _has_error_result(result):
                                exec_context.clear_code_cache()
                        else:
                            result = execute_tool(tool_name, tool_args)

                        print(" done")
                        session_tracker.track_tool_call(tool_name, tool_args)

                        messages.append({
                            "role": "tool",
                            "name": tool_name,
                            "content": result
                        })

                # Check for task completion
                if "TASK_COMPLETE" in content or "task complete" in content.lower():
                    print(f"\n  ✅ Task completed")
                    plan.mark_completed(content)
                    if state_manager:
                        state_manager.on_task_completed(current_task)
                    session_tracker.track_task_completed(current_task.description)
                    task_complete = True
                    break

            if not task_complete and task_iterations >= max_task_iterations:
                print(f"\n  ⚠️ Task exceeded iteration limit")
                plan.mark_task_stopped(current_task)

            # Trim message history
            messages, _ = _trim_history_with_notice(messages, max_recent=CONTEXT_WINDOW_HISTORY, tracker=session_tracker)

    finally:
        # Cleanup
        stop_streaming_input()
        streaming_manager.stop()

    # Print summary
    print("\n" + "=" * 60)
    print("EXECUTION SUMMARY")
    print("=" * 60)
    print(plan.get_summary())

    for i, task in enumerate(plan.tasks, 1):
        status_icon = {
            TaskStatus.COMPLETED: "✓",
            TaskStatus.FAILED: "✗",
            TaskStatus.IN_PROGRESS: "→",
            TaskStatus.PENDING: "○",
            TaskStatus.STOPPED: "⏸"
        }.get(task.status, "?")
        print(f"{status_icon} {i}. {task.description} [{task.status.value}]")

    print("=" * 60)

    # Show message queue stats
    stats = message_queue.get_stats()
    if stats["total_submitted"] > 0:
        print(f"\n📊 User messages: {stats['total_submitted']} submitted, {stats['total_processed']} processed")

    return all(t.status == TaskStatus.COMPLETED for t in plan.tasks)
