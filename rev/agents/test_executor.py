import json
from typing import Optional

from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool
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

        print(f"  → TestExecutorAgent will run command: '{command}'")
        
        try:
            result = execute_tool("run_cmd", {"command": command})
            # Check if the command execution itself indicates a failure (e.g., non-zero exit code)
            # For now, we'll assume any exception from execute_tool is a failure
            return result
        except Exception as e:
            error_msg = f"Error executing test command: {e}"
            context.add_error(error_msg)
            self.request_replan(context, "Test command execution failed", detailed_reason=error_msg)
            return error_msg
