import json
import re
from typing import Optional, Dict, Any

from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_last_tool_call
from rev.core.context import RevContext


class TestExecutorAgent(BaseAgent):
    """
    A sub-agent that specializes in running tests and lightweight execution checks.
    """

    def _select_command(self, description: str) -> tuple[str, Dict[str, Any]]:
        desc_lower = (description or "").lower()

        parts = (description or "").split()
        test_path = None
        for part in parts:
            if "tests/" in part or "tests\\" in part:
                test_path = part
                break

        command = "pytest"
        if test_path:
            command = f"pytest {test_path}"
        return command, {"timeout": 600}

    def _maybe_run_import_smoke(self, description: str) -> Optional[str]:
        """Run a quick import smoke test before full pytest when imports are the focus."""
        desc_lower = (description or "").lower()
        if "import" not in desc_lower:
            return None

        desc = description or ""
        module_candidates: list[str] = []
        module_candidates.extend(
            re.findall(
                r"\bfrom\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s+import\b",
                desc,
            )
        )
        module_candidates.extend(
            re.findall(
                r"\bimport\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b",
                desc,
            )
        )
        module_candidates = [m.strip() for m in module_candidates if m and m.strip()]
        if not module_candidates:
            return None

        module = module_candidates[0]

        wants_pytest = any(token in desc_lower for token in ("pytest", "run tests", "unit test", "test suite"))
        import_only = ("import" in desc_lower) and not wants_pytest

        smoke_cmd = f'python -c "import {module}"'
        print(f"  -> Running smoke test: {smoke_cmd}")
        result = execute_tool("run_cmd", {"command": smoke_cmd})
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            payload = {}

        rc = payload.get("rc")
        if isinstance(rc, int) and rc != 0:
            print("  [!] Smoke test failed; skipping pytest until import issues are resolved.")
            return result

        print("  [OK] Smoke test passed")
        if import_only:
            return json.dumps(
                {
                    "rc": 0,
                    "stdout": f"Smoke import OK: {module}",
                    "stderr": "",
                    "command": smoke_cmd,
                    "kind": "import_smoke",
                }
            )
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
        """Executes a test-related task."""
        print(f"TestExecutorAgent executing task: {task.description}")

        smoke_result = self._maybe_run_import_smoke(task.description)
        if smoke_result is not None:
            return smoke_result

        command, run_opts = self._select_command(task.description)
        is_pytest = command.strip().lower().startswith("pytest")

        if is_pytest and not self._should_run_pytest(context):
            warning = "[SKIPPED_TESTS] No code changes detected since last run; skipping pytest."
            print(f"  [WARN]  {warning}")
            return json.dumps(
                {
                    "skipped": True,
                    "kind": "skipped_tests",
                    "reason": "no code changes detected since last run",
                    "command": command,
                    "last_test_iteration": context.get_agent_state("last_test_iteration"),
                    "last_test_rc": context.get_agent_state("last_test_rc"),
                    "last_code_change_iteration": context.get_agent_state("last_code_change_iteration"),
                    "warning": warning,
                }
            )

        print(f"  -> Running: {command}")

        try:
            tool_args: Dict[str, Any] = {"command": command}
            if isinstance(run_opts, dict) and run_opts.get("timeout"):
                tool_args["timeout"] = run_opts["timeout"]

            result = execute_tool("run_cmd", tool_args)
            context.set_agent_state("last_test_iteration", context.get_agent_state("current_iteration", 0))

            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                # Normalize rc so verification always has an exit code to inspect.
                if not isinstance(payload.get("rc"), int):
                    rc_fallback = payload.get("returncode")
                    if isinstance(rc_fallback, int):
                        payload["rc"] = rc_fallback
                    elif payload.get("timeout") or payload.get("blocked"):
                        # leave as-is; verifier will surface the error
                        pass
                    else:
                        payload["rc"] = 1
                if isinstance(payload.get("rc"), int):
                    context.set_agent_state("last_test_rc", payload.get("rc"))
                result = json.dumps(payload)
            return result
        except Exception as e:
            error_msg = f"Error executing test command: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Test command execution failed", detailed_reason=error_msg)
            return error_msg
