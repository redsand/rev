from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool
from rev.core.context import RevContext

class TestExecutorAgent(BaseAgent):
    """
    A sub-agent that specializes in running tests.
    """

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
