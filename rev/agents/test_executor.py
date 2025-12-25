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
2. COMMAND SELECTION PRIORITY (in order):
   a) If task description contains an explicit command (npm test, pytest, yarn test, go test, etc.), USE THAT EXACT COMMAND
   b) If task says to validate/test Node.js/JavaScript files, use npm test (NOT pytest)
   c) If task says to validate/test Python files, use pytest
   d) Check workspace context for package.json (use npm test), go.mod (use go test), Cargo.toml (use cargo test)
3. NEVER use pytest for Node.js/JavaScript projects (files ending in .js, .ts, .jsx, .tsx)
4. Use the provided 'System Information' (OS, Platform, Shell Type) to choose the correct command syntax.
5. For complex validation, you are encouraged to run platform-specific scripts (.ps1 for Windows, .sh for POSIX) if they exist or were created.
6. Prefer `run_tests` for standard test suites (pytest, npm test, etc.) and `run_cmd` for general validation or script execution.
7. If the task is to "install" something, use `run_cmd`.
8. Your response MUST be a single, valid JSON object representing the tool call.

Example 1 - Task says "npm test" explicitly:
Task: "Run npm test to validate the changes"
{
  "tool_name": "run_tests",
  "arguments": {
    "cmd": "npm test"
  }
}

Example 2 - Task mentions .js file (Node.js project):
Task: "Run tests to validate changes to app.js"
{
  "tool_name": "run_tests",
  "arguments": {
    "cmd": "npm test"
  }
}

Example 3 - Python project:
Task: "Run tests to validate auth.py"
{
  "tool_name": "run_tests",
  "arguments": {
    "cmd": "pytest tests/test_auth.py",
    "timeout": 300
  }
}

Example 4 - PowerShell script:
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
                # Try to recover tool call from text content before falling back to heuristics
                from rev.core.tool_call_recovery import recover_tool_call_from_text

                text_content = response.get("message", {}).get("content", "") if response else ""
                if text_content:
                    recovered = recover_tool_call_from_text(
                        text_content,
                        allowed_tools=['run_tests', 'run_cmd', 'file_exists', 'list_dir']
                    )
                    if recovered:
                        print(f"  -> Recovered tool call from text: {recovered.name}")

                        # CRITICAL FIX: Validate command matches project type (recovery path)
                        if recovered.name in ("run_tests", "run_cmd"):
                            cmd = recovered.arguments.get("cmd", "")
                            corrected_cmd = self._validate_and_correct_test_command(cmd, task, context)
                            if corrected_cmd != cmd:
                                print(f"  [!] Correcting test command: {cmd} -> {corrected_cmd}")
                                recovered.arguments["cmd"] = corrected_cmd

                        raw_result = execute_tool(recovered.name, recovered.arguments, agent_name="test_executor")

                        # Record test iteration for skip logic
                        if recovered.name in ("run_tests", "run_cmd") and ("test" in str(recovered.arguments).lower() or "pytest" in str(recovered.arguments).lower()):
                            context.set_agent_state("last_test_iteration", context.get_agent_state("current_iteration", 0))
                            try:
                                res_data = json.loads(raw_result)
                                if isinstance(res_data, dict) and "rc" in res_data:
                                    context.set_agent_state("last_test_rc", res_data["rc"])
                            except: pass

                        return build_subagent_output(
                            agent_name="TestExecutorAgent",
                            tool_name=recovered.name,
                            tool_args=recovered.arguments,
                            tool_output=raw_result,
                            context=context,
                            task_id=task.task_id,
                        )

                # Only fall back to heuristics if recovery also failed
                return self._execute_fallback_heuristic(task, context)

            tool_call = response["message"]["tool_calls"][0]
            tool_name = tool_call['function']['name']
            arguments = tool_call['function']['arguments']

            if isinstance(arguments, str):
                try: arguments = json.loads(arguments)
                except: pass

            # CRITICAL FIX: Validate command matches project type
            if tool_name in ("run_tests", "run_cmd"):
                cmd = arguments.get("cmd", "")
                corrected_cmd = self._validate_and_correct_test_command(cmd, task, context)
                if corrected_cmd != cmd:
                    print(f"  [!] Correcting test command: {cmd} -> {corrected_cmd}")
                    arguments["cmd"] = corrected_cmd

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
        last_test_rc = context.get_agent_state("last_test_rc", None)

        # Never skip first run
        if last_test_iteration == 0:
            return False

        # Never skip if last test failed (rc != 0) - need to retry with correct command
        if last_test_rc is not None and last_test_rc != 0:
            return False

        # Only skip if no edits happened since last SUCCESSFUL test run
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
                    # Detect project type before defaulting to pytest
                    from pathlib import Path
                    workspace_root = context.workspace_root if hasattr(context, 'workspace_root') else Path.cwd()
                    root = Path(workspace_root) if workspace_root else Path.cwd()

                    if (root / "package.json").exists():
                        cmd = "npm test"
                    elif (root / "yarn.lock").exists():
                        cmd = "yarn test"
                    elif (root / "pnpm-lock.yaml").exists():
                        cmd = "pnpm test"
                    elif (root / "go.mod").exists():
                        cmd = "go test ./..."
                    elif (root / "Cargo.toml").exists():
                        cmd = "cargo test"
                    else:
                        # Final fallback to pytest for Python projects
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

    def _validate_and_correct_test_command(self, cmd: str, task: Task, context: RevContext) -> str:
        """
        Validate that the test command matches the project type.
        Corrects obvious mismatches (e.g., pytest on Node.js projects).

        Priority 1: Check task description for explicit command
        Priority 2: Check task description for file extensions
        Priority 3: Check workspace for project type markers
        """
        from pathlib import Path

        cmd_lower = cmd.lower().strip()
        desc = (task.description or "")
        desc_lower = desc.lower()

        # Priority 1: If task explicitly mentions a command, use it
        explicit_commands = {
            "npm test": "npm test",
            "yarn test": "yarn test",
            "pnpm test": "pnpm test",
            "pytest": "pytest",
            "go test": "go test ./...",
            "cargo test": "cargo test",
        }
        for explicit, corrected in explicit_commands.items():
            if explicit in desc_lower and explicit not in cmd_lower:
                # Task says one thing, LLM chose another - trust the task
                return corrected

        # Priority 2: Check file extensions mentioned in task
        is_nodejs_task = any(ext in desc_lower for ext in [".js", ".ts", ".jsx", ".tsx", "app.js", "index.js", "package.json"])
        is_python_task = any(ext in desc_lower for ext in [".py", "pytest", "test_"])
        is_go_task = ".go" in desc_lower or "go.mod" in desc_lower
        is_rust_task = ".rs" in desc_lower or "cargo.toml" in desc_lower

        # If task mentions Node.js files but command is pytest, correct it
        if is_nodejs_task and "pytest" in cmd_lower:
            workspace_root = context.workspace_root if hasattr(context, 'workspace_root') else Path.cwd()
            root = Path(workspace_root) if workspace_root else Path.cwd()

            if (root / "package.json").exists():
                return "npm test"
            elif (root / "yarn.lock").exists():
                return "yarn test"
            elif (root / "pnpm-lock.yaml").exists():
                return "pnpm test"
            else:
                return "npm test"  # Default for Node.js

        # If task mentions Python files but command is npm test, correct it
        if is_python_task and any(npm_cmd in cmd_lower for npm_cmd in ["npm test", "yarn test", "pnpm test"]):
            return "pytest"

        # If task mentions Go files but command is wrong
        if is_go_task and "pytest" in cmd_lower:
            return "go test ./..."

        # If task mentions Rust files but command is wrong
        if is_rust_task and "pytest" in cmd_lower:
            return "cargo test"

        # Priority 3: If no explicit hints, check workspace for project type
        if "pytest" in cmd_lower:
            workspace_root = context.workspace_root if hasattr(context, 'workspace_root') else Path.cwd()
            root = Path(workspace_root) if workspace_root else Path.cwd()

            # If workspace has package.json but command is pytest, likely wrong
            if (root / "package.json").exists():
                # Check if there's also a Python project (requirements.txt, setup.py, etc.)
                has_python = any((root / f).exists() for f in ["requirements.txt", "setup.py", "pyproject.toml", "pytest.ini"])
                if not has_python:
                    # Pure Node.js project, pytest is wrong
                    return "npm test"

        # No correction needed
        return cmd
