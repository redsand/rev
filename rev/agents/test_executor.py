import json
import re
from typing import Optional, Dict, Any, List

from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools, get_last_tool_call
from rev.core.context import RevContext
from rev.llm.client import ollama_chat
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output

TEST_EXECUTOR_SYSTEM_PROMPT = """You are a specialized Test Executor agent. Your purpose is to run tests, validate implementations, and perform execution checks.

You will be given a task description and repository context. Your goal is to choose and execute the most appropriate test or validation command.

CRITICAL RULES:
1. You MUST respond with a single tool call in JSON format. Do NOT provide any other text, explanations, or markdown.
2. Use the provided 'System Information' (OS, Platform, Shell Type) to choose the correct command syntax.
3. For complex validation, you are encouraged to run platform-specific scripts (.ps1 for Windows, .sh for POSIX) if they exist or were created.
4. Prefer `run_tests` for standard test suites (pytest, npm test, etc.) and `run_cmd` for general validation or script execution.
5. If the task is to "install" something, use `run_cmd`.
6. Your response MUST be a single, valid JSON object representing the tool call.

Example for running pytest:
{
  "tool_name": "run_tests",
  "arguments": {
    "cmd": "pytest tests/test_auth.py",
    "timeout": 300
  }
}

Example for running a PowerShell script:
{
  "tool_name": "run_cmd",
  "arguments": {
    "cmd": "powershell ./validate_fix.ps1"
  }
}

Now, generate the tool call to execute the test or validation.
"""

class TestExecutorAgent(BaseAgent):
    """
    A sub-agent that specializes in running tests and lightweight execution checks.
    Uses LLM-driven command selection for maximum flexibility across platforms.
    """

    def execute(self, task: Task, context: RevContext) -> str:
        """Executes a test-related task using LLM guidance."""
        print(f"TestExecutorAgent executing task: {task.description}")

        # Track recovery attempts
        recovery_attempts = self.increment_recovery_attempts(task, context)

        # 1. Check for skipped tests (efficiency optimization)
        if self._should_skip_pytest(task, context):
            warning = "[SKIPPED_TESTS] No code changes detected since last run; skipping full test suite."
            print(f"  [WARN]  {warning}")
            return json.dumps({
                "skipped": True,
                "reason": "no code changes detected",
                "warning": warning
            })

        # 2. Build context and tools
        all_tools = get_available_tools()
        test_tool_names = ['run_tests', 'run_cmd', 'file_exists', 'list_dir']
        
        rendered_context, selected_tools, _bundle = build_context_and_tools(
            task,
            context,
            tool_universe=all_tools,
            candidate_tool_names=test_tool_names,
            max_tools=4,
        )

        messages = [
            {"role": "system", "content": TEST_EXECUTOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {task.description}\n\nSelected Context:\n{rendered_context}"}
        ]

        try:
            response = ollama_chat(messages, tools=selected_tools)
            
            if not response or "message" not in response or "tool_calls" not in response["message"]:
                # Fallback to heuristics if LLM fails to provide tool call
                return self._execute_fallback_heuristic(task, context)

            tool_call = response["message"]["tool_calls"][0]
            tool_name = tool_call['function']['name']
            arguments = tool_call['function']['arguments']
            
            if isinstance(arguments, str):
                try: arguments = json.loads(arguments)
                except: pass

            print(f"  -> Executing: {tool_name} {arguments}")
            raw_result = execute_tool(tool_name, arguments, agent_name="test_executor")
            
            # Record test iteration for skip logic
            if tool_name in ("run_tests", "run_cmd") and ("test" in str(arguments).lower() or "pytest" in str(arguments).lower()):
                context.set_agent_state("last_test_iteration", context.get_agent_state("current_iteration", 0))
                try:
                    res_data = json.loads(raw_result)
                    if isinstance(res_data, dict) and "rc" in res_data:
                        context.set_agent_state("last_test_rc", res_data["rc"])
                except: pass

            return build_subagent_output(
                agent_name="TestExecutorAgent",
                tool_name=tool_name,
                tool_args=arguments,
                tool_output=raw_result,
                context=context,
                task_id=task.task_id,
            )

        except Exception as e:
            error_msg = f"Error in TestExecutorAgent: {e}"
            print(f"  [!] {error_msg}")
            return self._execute_fallback_heuristic(task, context)

    def _should_skip_pytest(self, task: Task, context: RevContext) -> bool:
        """Heuristic to skip full pytest suites if nothing changed."""
        desc_lower = (task.description or "").lower()
        if "pytest" not in desc_lower and "test suite" not in desc_lower:
            return False

        last_edit_iteration = context.get_agent_state("last_code_change_iteration", 0)
        last_test_iteration = context.get_agent_state("last_test_iteration", 0)
        
        # Never skip first run
        if last_test_iteration == 0:
            return False
            
        # Only skip if no edits happened since last test run
        return last_test_iteration >= last_edit_iteration

    def _execute_fallback_heuristic(self, task: Task, context: RevContext) -> str:
        """Deterministic fallback if LLM selection fails."""
        desc = (task.description or "")
        desc_lower = desc.lower()

        cmd = None
        explicit_cmds = [
            "npm ci",
            "npm install",
            "npm test",
            "yarn install",
            "yarn test",
            "pnpm install",
            "pnpm test",
            "pytest",
            "go test",
        ]
        for explicit in explicit_cmds:
            if explicit in desc_lower:
                cmd = explicit if explicit != "go test" else "go test ./..."
                break

        if cmd is None:
            if "install" in desc_lower:
                if "yarn" in desc_lower:
                    cmd = "yarn install"
                elif "pnpm" in desc_lower:
                    cmd = "pnpm install"
                elif any(token in desc_lower for token in ("npm", "node", "frontend", "package.json")):
                    cmd = "npm install"

            if cmd is None:
                if "npm" in desc_lower or "jest" in desc_lower or "vitest" in desc_lower:
                    cmd = "npm test"
                elif "yarn" in desc_lower:
                    cmd = "yarn test"
                elif "pnpm" in desc_lower:
                    cmd = "pnpm test"
                elif "go test" in desc_lower:
                    cmd = "go test ./..."
                else:
                    cmd = "pytest"

        workdir = self._extract_workdir_hint(desc)
        cmd = self._apply_workdir(cmd, workdir)

        print(f"  [i] Using fallback heuristic: {cmd}")
        raw_result = execute_tool("run_cmd", {"cmd": cmd})
        return build_subagent_output(
            agent_name="TestExecutorAgent",
            tool_name="run_cmd",
            tool_args={"cmd": cmd},
            tool_output=raw_result,
            context=context,
            task_id=task.task_id,
        )

    def _extract_workdir_hint(self, desc: str) -> Optional[str]:
        """Best-effort guess for a working directory hinted in task text."""
        if not desc:
            return None
        patterns = [
            r"(?:in|within|under|inside)\s+(?:the\s+)?([a-zA-Z0-9_./\\-]+)\s+(?:directory|dir|folder)\b",
            r"\b([a-zA-Z0-9_./\\-]+)\s+(?:directory|dir|folder)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, desc, re.IGNORECASE)
            if match:
                candidate = match.group(1).rstrip(".,;:")
                if candidate:
                    return candidate
        for known in ("frontend", "client", "web", "ui", "backend", "server", "api"):
            if re.search(rf"\b{known}\b", desc, re.IGNORECASE):
                return known
        return None

    def _apply_workdir(self, cmd: str, workdir: Optional[str]) -> str:
        """Inject a working directory flag for supported package managers."""
        if not workdir:
            return cmd
        if re.search(r"\b(--prefix|--cwd|--dir|-C)\b", cmd):
            return cmd
        workdir_arg = workdir
        if " " in workdir_arg or "\t" in workdir_arg:
            workdir_arg = f"\"{workdir_arg}\""
        if cmd.startswith("npm "):
            return f"npm --prefix {workdir_arg} {cmd[4:]}"
        if cmd.startswith("yarn "):
            return f"yarn --cwd {workdir_arg} {cmd[5:]}"
        if cmd.startswith("pnpm "):
            return f"pnpm --dir {workdir_arg} {cmd[5:]}"
        return cmd
