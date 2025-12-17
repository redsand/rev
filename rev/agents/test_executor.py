import json
from typing import Optional, Dict, Any

from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_last_tool_call
from rev.core.context import RevContext

class TestExecutorAgent(BaseAgent):
    """
    A sub-agent that specializes in running tests.
    """

    def _maybe_run_import_smoke(self, description: str) -> Optional[str]:
        """Run a quick import smoke test before full pytest when imports are the focus."""
        desc_lower = description.lower()
        if "import" not in desc_lower:
            return None

        module = None
        if "lib/analysts" in desc_lower or "lib.analysts" in desc_lower or "analyst class" in desc_lower:
            module = "lib.analysts"

        if not module:
            return None

        smoke_cmd = f'python -c "import {module}"'
        print(f"  → Running smoke test: {smoke_cmd}")
        result = execute_tool("run_cmd", {"command": smoke_cmd})
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            payload = {}

        rc = payload.get("rc")
        if isinstance(rc, int) and rc != 0:
            print("  ✗ Smoke test failed; skipping pytest until import issues are resolved.")
            return result

        print("  ✓ Smoke test passed")
        return None

    def _last_change_context(self, context: RevContext) -> Optional[Dict[str, Any]]:
        """Fetch last known file modifications from the session summary if available."""
        session = getattr(context, "state_manager", None)
        if not session:
            return None
        tracker = getattr(session, "session_tracker", None)
        if not tracker:
            return None
        summary = getattr(tracker, "summary", None)
        if not summary:
            return None
        return {
            "files_modified": getattr(summary, "files_modified", []),
            "files_created": getattr(summary, "files_created", []),
            "files_deleted": getattr(summary, "files_deleted", []),
        }

    def _should_run_pytest(self, context: RevContext) -> bool:
        """Skip pytest if no files were modified/created/deleted since last run."""
        last_call = get_last_tool_call() or {}
        if (last_call.get("name") or "").lower() in {"write_file", "replace_in_file", "apply_patch", "append_to_file"}:
            return True

        last_edit_iteration = context.get_agent_state("last_code_change_iteration", 0)
        last_test_iteration = context.get_agent_state("last_test_iteration", 0)
        if last_test_iteration == 0:
            return True
        if last_edit_iteration > last_test_iteration:
            return True

        change_context = self._last_change_context(context)
        if not change_context:
            return False

        files_touched = (
            change_context.get("files_modified")
            or change_context.get("files_created")
            or change_context.get("files_deleted")
        )
        return bool(files_touched)

    def execute(self, task: Task, context: RevContext) -> str:
        """
        Executes a test-related task.
        """
        print(f"TestExecutorAgent executing task: {task.description}")

        parts = task.description.split()
        test_path = None
        for part in parts:
            if "tests/" in part:
                test_path = part
                break
        
        command = "pytest"
        if test_path:
            command = f"pytest {test_path}"

        smoke_result = self._maybe_run_import_smoke(task.description)
        if smoke_result is not None:
            return smoke_result

        if not self._should_run_pytest(context):
            warning = "[SKIPPED_TESTS] No code changes detected since last run; skipping pytest."
            print(f"  ⚠️  {warning}")
            return warning

        print(f"  → TestExecutorAgent will run command: '{command}'")
        
        try:
            result = execute_tool("run_cmd", {"command": command})
            context.set_agent_state("last_test_iteration", context.get_agent_state("current_iteration", 0))
            # Check if the command execution itself indicates a failure (e.g., non-zero exit code)
            # For now, we'll assume any exception from execute_tool is a failure
            return result
        except Exception as e:
            error_msg = f"Error executing test command: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Test command execution failed", detailed_reason=error_msg)
            return error_msg
