import json
import re
import shlex
from pathlib import Path
from typing import Optional, Dict, Any, List

from rev.agents.base import BaseAgent
from rev.models.task import Task
from rev.tools.registry import execute_tool, get_available_tools, get_last_tool_call
from rev.core.context import RevContext
from rev.llm.client import ollama_chat
from rev.agents.context_provider import build_context_and_tools
from rev.agents.subagent_io import build_subagent_output
from rev.tools.project_types import detect_test_command
from rev import config
from rev.core.tool_call_recovery import recover_tool_call_from_text, recover_tool_call_from_text_lenient
from rev.core.tool_call_retry import retry_tool_call_with_response_format
from rev.execution import quick_verify

TEST_EXECUTOR_SYSTEM_PROMPT = """You are a specialized Test Executor agent. Your sole purpose is to run tests and validate implementations by calling appropriate tools.

âš ï¸ CRITICAL WARNING - TOOL EXECUTION IS MANDATORY âš ï¸
YOU MUST CALL A TOOL. DO NOT RETURN EXPLANATORY TEXT. DO NOT DESCRIBE WHAT YOU WOULD DO.
IF YOU RETURN TEXT INSTEAD OF A TOOL CALL, THE TASK WILL FAIL PERMANENTLY.

Your response must be ONLY a JSON tool call. Example:
{
  "tool_name": "run_tests",
  "arguments": {
    "cmd": "npm test -- tests/example.test.js"
  }
}

DO NOT wrap the JSON in markdown. DO NOT add any other text before or after the JSON.
Analyze task and context carefully. Respond with ONLY JSON.
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
            response = ollama_chat(messages, tools=selected_tools, supports_tools=True, tool_choice="required")

            if not response or "message" not in response or "tool_calls" not in response["message"]:
                # Try to recover tool call from text content before falling back to heuristics
                text_content = response.get("message", {}).get("content", "") if response else ""
                allowed_tools = ['run_tests', 'run_cmd', 'file_exists', 'list_dir']
                recovered = recover_tool_call_from_text(
                    text_content,
                    allowed_tools=allowed_tools,
                )
                if not recovered:
                    recovered = recover_tool_call_from_text_lenient(
                        text_content,
                        allowed_tools=allowed_tools,
                    )
                    if recovered:
                        print("  [WARN] TestExecutorAgent: using lenient tool call recovery from text output")
                if not recovered:
                    recovered = retry_tool_call_with_response_format(
                        messages,
                        selected_tools,
                        allowed_tools=allowed_tools,
                    )
                    if recovered:
                        print(f"  -> Retried tool call with JSON format: {recovered.name}")
                if recovered:
                    print(f"  -> Recovered tool call from text: {recovered.name}")

                    if config.TEST_EXECUTOR_COMMAND_CORRECTION_ENABLED and recovered.name in ("run_tests", "run_cmd"):
                        cmd = recovered.arguments.get("cmd", "")
                        corrected_cmd = self._validate_and_correct_test_command(cmd, task, context)
                        if corrected_cmd != cmd:
                            print(f"  [!] Correcting test command: {cmd} -> {corrected_cmd}")
                            recovered.arguments["cmd"] = corrected_cmd

                    blocked = self._block_non_terminating_command(recovered.name, recovered.arguments, task, context)
                    if blocked:
                        return blocked

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

                # Prefer an explicit command in the task description before any heuristics.
                explicit_cmd = self._extract_explicit_command(task.description or "")
                if explicit_cmd:
                    return self._execute_explicit_command(task, context, explicit_cmd)

                # Only fall back to heuristics if recovery also failed
                if not config.TEST_EXECUTOR_FALLBACK_ENABLED:
                    error_payload = json.dumps({
                        "error": "Fallback heuristics disabled; no explicit command found in task description.",
                        "blocked": True,
                        "rc": 1,
                    })
                    return build_subagent_output(
                        agent_name="TestExecutorAgent",
                        tool_name="run_cmd",
                        tool_args={"cmd": ""},
                        tool_output=error_payload,
                        context=context,
                        task_id=task.task_id,
                    )
                return self._execute_fallback_heuristic(task, context)

            tool_call = response["message"]["tool_calls"][0]
            tool_name = tool_call['function']['name']
            arguments = tool_call['function']['arguments']

            if isinstance(arguments, str):
                try: arguments = json.loads(arguments)
                except: pass

            if config.TEST_EXECUTOR_COMMAND_CORRECTION_ENABLED and tool_name in ("run_tests", "run_cmd"):
                cmd = arguments.get("cmd", "")
                corrected_cmd = self._validate_and_correct_test_command(cmd, task, context)
                if corrected_cmd != cmd:
                    print(f"  [!] Correcting test command: {cmd} -> {corrected_cmd}")
                    try:
                        log_event = {
                            "action": "command_correction",
                            "original": cmd,
                            "corrected": corrected_cmd,
                            "task_id": task.task_id,
                        }
                        print(f"  [log] {json.dumps(log_event, ensure_ascii=False)}")
                    except Exception:
                        pass
                    arguments["cmd"] = corrected_cmd

            blocked = self._block_non_terminating_command(tool_name, arguments, task, context)
            if blocked:
                return blocked

            print(f"  -> Executing: {tool_name} {arguments}")
            raw_result = execute_tool(tool_name, arguments, agent_name="test_executor")
            # Surface timeouts clearly to the user/verification layers.
            try:
                parsed = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            except Exception:
                parsed = None
            if isinstance(parsed, dict) and (parsed.get("timed_out") or parsed.get("timeout") or parsed.get("timeout_decision")):
                # Signal that a remediation should be planned (e.g., safer test command).
                parsed["needs_fix"] = True
                parsed["log_note"] = {
                    "message": "Test command timed out; captured tails for visibility",
                    "stdout_tail": parsed.get("stdout", "")[-500:] if isinstance(parsed.get("stdout"), str) else "",
                    "stderr_tail": parsed.get("stderr", "")[-500:] if isinstance(parsed.get("stderr"), str) else "",
                    "cmd": arguments.get("cmd"),
                }
                timeout_seconds = None
                if isinstance(arguments, dict):
                    timeout_seconds = arguments.get("timeout")
                if not timeout_seconds and isinstance(parsed.get("timeout_initial"), dict):
                    timeout_seconds = parsed.get("timeout_initial", {}).get("timeout_seconds")
                # Preserve stdout/stderr tails but keep output concise
                stdout_tail = ""
                stderr_tail = ""
                if isinstance(parsed.get("stdout"), str):
                    stdout_tail = parsed["stdout"][-500:]
                if isinstance(parsed.get("stderr"), str):
                    stderr_tail = parsed["stderr"][-500:]
                parsed.update({
                    "blocked": True,
                    "reason": parsed.get("reason") or "Command timed out",
                    "timeout_seconds": timeout_seconds,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                })
                raw_result = json.dumps(parsed, ensure_ascii=False)
            rerun = self._maybe_rerun_no_tests(tool_name, arguments, raw_result, task, context)
            if rerun:
                tool_name, arguments, raw_result = rerun
            
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
            if not config.TEST_EXECUTOR_FALLBACK_ENABLED:
                explicit_cmd = self._extract_explicit_command(task.description or "")
                if explicit_cmd:
                    return self._execute_explicit_command(task, context, explicit_cmd)
                error_payload = json.dumps({
                    "error": error_msg,
                    "blocked": True,
                    "rc": 1,
                })
                return build_subagent_output(
                    agent_name="TestExecutorAgent",
                    tool_name="run_cmd",
                    tool_args={"cmd": ""},
                    tool_output=error_payload,
                    context=context,
                    task_id=task.task_id,
                )
            return self._execute_fallback_heuristic(task, context)

    def _maybe_rerun_no_tests(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        raw_result: str,
        task: Task,
        context: RevContext,
    ) -> Optional[tuple[str, Dict[str, Any], str]]:
        if tool_name not in ("run_tests", "run_cmd"):
            return None
        payload = self._parse_tool_payload(raw_result)
        if not payload:
            return None
        output = f"{payload.get('stdout', '')}{payload.get('stderr', '')}".lower()
        if not self._is_no_tests_output(output):
            return None

        cmd = arguments.get("cmd", "")
        if not isinstance(cmd, (str, list)):
            return None

        test_path = self._extract_test_path(cmd if isinstance(cmd, str) else " ".join(cmd))
        if not test_path:
            test_path = self._extract_test_path(task.description or "")

        cmd_parts = (
            [str(part) for part in cmd if part is not None]
            if isinstance(cmd, list)
            else shlex.split(cmd)
        )
        if test_path and test_path not in cmd_parts:
            cmd_parts = list(cmd_parts) + [test_path]

        try:
            from rev.execution import quick_verify
            fallback_cmd = quick_verify._attempt_no_tests_fallback(
                cmd_parts,
                str(payload.get("stdout", "") or ""),
                str(payload.get("stderr", "") or ""),
                arguments.get("cwd"),
            )
        except Exception:
            fallback_cmd = None

        if fallback_cmd and fallback_cmd != cmd_parts:
            print("  [i] No tests found; retrying with explicit test paths")
            rerun_args = dict(arguments)
            rerun_args["cmd"] = fallback_cmd
            rerun_result = execute_tool(tool_name, rerun_args, agent_name="test_executor")
            return tool_name, rerun_args, rerun_result

        desc_lower = (task.description or "").lower()
        if "jest" not in str(cmd).lower() and "jest" not in desc_lower:
            return None
        if "--runtestsbypath" in str(cmd).lower():
            return None

        if not test_path:
            return None

        rerun_cmd = self._build_jest_run_by_path_cmd(str(cmd), test_path)
        if rerun_cmd == str(cmd):
            return None

        print("  [i] No tests found; retrying with --runTestsByPath")
        rerun_args = dict(arguments)
        rerun_args["cmd"] = rerun_cmd
        rerun_result = execute_tool(tool_name, rerun_args, agent_name="test_executor")
        return tool_name, rerun_args, rerun_result

    @staticmethod
    def _parse_tool_payload(raw_result: str) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_result, str) or not raw_result.strip():
            return None
        try:
            payload = json.loads(raw_result)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _is_no_tests_output(output: str) -> bool:
        if not output:
            return False
        return any(
            token in output
            for token in (
                "no tests found",
                "no tests ran",
                "no tests collected",
                "collected 0 items",
            )
        )

    @staticmethod
    def _extract_test_path(text: str) -> Optional[str]:
        if not text:
            return None
        matches = re.findall(
            r"([A-Za-z0-9_./\\\\-]+\.(?:test|spec)\.[A-Za-z0-9]+)",
            text,
        )
        if not matches:
            return None
        return max(matches, key=len)

    @staticmethod
    def _build_jest_run_by_path_cmd(cmd: str, test_path: str) -> str:
        cleaned = cmd
        pattern = re.compile(rf"(\"|')?{re.escape(test_path)}(\\1)?")
        cleaned = pattern.sub("", cleaned).strip()
        cleaned = re.sub(r"\\s+", " ", cleaned)
        return f"{cleaned} --runTestsByPath {test_path}".strip()

    def _detect_non_terminating_command(self, cmd: str | list[str]) -> Optional[str]:
        cmd_text = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        if not cmd_text.strip():
            return None
        try:
            tokens = [str(t) for t in cmd] if isinstance(cmd, list) else shlex.split(cmd_text)
        except ValueError:
            tokens = cmd_text.split()
        tokens_lower = [t.lower() for t in tokens]

        vitest_idx = None
        for idx, tok in enumerate(tokens_lower):
            if tok.endswith("vitest") or tok.endswith("vitest.cmd"):
                vitest_idx = idx
                break
        if vitest_idx is not None:
            has_run_flag = any(tok == "--run" or tok.startswith("--run=") for tok in tokens_lower)
            has_run_subcommand = any(tok == "run" for tok in tokens_lower[vitest_idx + 1 : vitest_idx + 3])
            watch_disabled = any(tok in ("--watch=false", "--watch=0") for tok in tokens_lower)
            if not watch_disabled and "--watch" in tokens_lower:
                for idx, tok in enumerate(tokens_lower):
                    if tok == "--watch" and idx + 1 < len(tokens_lower):
                        if tokens_lower[idx + 1] in ("false", "0", "no"):
                            watch_disabled = True
                            break

            if not has_run_flag and not has_run_subcommand and not watch_disabled:
                return (
                    "Blocked non-terminating Vitest command. Use `npx vitest run <file>` or "
                    "`npx vitest --run <file>` (or disable watch with `--watch=false`)."
                )
        return None

    def _block_non_terminating_command(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        task: Task,
        context: RevContext,
    ) -> Optional[str]:
        if tool_name not in ("run_cmd", "run_tests"):
            return None
        if not isinstance(arguments, dict):
            return None
        cmd = arguments.get("cmd")
        if not cmd:
            return None
        reason = self._detect_non_terminating_command(cmd)
        if not reason:
            reason = self._detect_non_terminating_test_script(cmd, task, context)
        if not reason:
            return None

        # Suggest a safe, targeted command to feed back to the LLM.
        suggested = None
        target_path = (
            self._extract_test_path(task.description or "")
            or context.get_agent_state("last_failing_test_file", "")
            or self._find_default_test_path(context)
        )
        if target_path:
            suggested = f"npx vitest run {target_path}"
        hint = f"{reason}"
        if suggested:
            hint += f" | Suggested non-interactive command: {suggested}"

        payload = json.dumps(
            {"rc": 1, "stdout": "", "stderr": hint, "blocked": True, "cmd": cmd},
            ensure_ascii=False,
        )
        return build_subagent_output(
            agent_name="TestExecutorAgent",
            tool_name=tool_name,
            tool_args=arguments,
            tool_output=payload,
            context=context,
            task_id=task.task_id,
        )

    def _detect_non_terminating_test_script(
        self,
        cmd: str | list[str],
        task: Task,
        context: RevContext,
    ) -> Optional[str]:
        cmd_text = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        if not cmd_text.strip():
            return None
        try:
            tokens = [str(t) for t in cmd] if isinstance(cmd, list) else shlex.split(cmd_text)
        except ValueError:
            tokens = cmd_text.split()
        if not tokens:
            return None

        tokens_lower = [t.lower() for t in tokens]
        package_manager = tokens_lower[0]
        if package_manager not in ("npm", "yarn", "pnpm"):
            return None

        script_name = None
        if len(tokens_lower) > 1 and tokens_lower[1] == "test":
            script_name = "test"
        elif len(tokens_lower) > 2 and tokens_lower[1] == "run":
            script_name = tokens_lower[2]

        if not script_name:
            return None

        if any(tok in ("--run", "--watch=false", "--watch=0") or tok.startswith("--run=") for tok in tokens_lower):
            return None

        from rev.tools.project_types import find_project_root

        root = find_project_root(config.ROOT)
        pkg_path = root / "package.json"
        if not pkg_path.exists():
            return None

        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        scripts = pkg.get("scripts")
        if not isinstance(scripts, dict):
            return None
        script_value = scripts.get(script_name)
        if not isinstance(script_value, str) or not script_value.strip():
            return None

        script_lower = script_value.lower()
        if "vitest" not in script_lower:
            return None
        if "vitest run" in script_lower or "--run" in script_lower:
            return None
        if "--watch=false" in script_lower or "--watch=0" in script_lower:
            return None

        test_path = self._extract_test_path(cmd_text) or self._extract_test_path(task.description or "")
        if test_path:
            suggestion = f"npx vitest run {test_path}"
        else:
            suggestion = "npx vitest run"

        return (
            "Blocked non-terminating test script: package.json runs vitest without --run/--watch=false. "
            f"Use `{suggestion}` (or pass `-- --run` to the test script)."
        )

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

        explicit_cmd = self._extract_explicit_command(desc)
        if explicit_cmd:
            cmd = self._maybe_target_test_command(explicit_cmd, task, context)
            workdir = self._extract_workdir_hint(desc)
            cmd = self._apply_workdir(cmd, workdir)
            blocked = self._block_non_terminating_command("run_cmd", {"cmd": cmd}, task, context)
            if blocked:
                return blocked
            print(f"  [i] Using explicit command from task: {cmd}")
            raw_result = execute_tool("run_cmd", {"cmd": cmd}, agent_name="test_executor")
            return build_subagent_output(
                agent_name="TestExecutorAgent",
                tool_name="run_cmd",
                tool_args={"cmd": cmd},
                tool_output=raw_result,
                context=context,
                task_id=task.task_id,
            )

        cmd = None
        explicit_patterns = [
            r"\bnpm\s+(?:install|ci)\b[^\n\r]*",
            r"\byarn\s+install\b[^\n\r]*",
            r"\bpnpm\s+install\b[^\n\r]*",
            r"\bpip\s+install\b[^\n\r]*",
            r"\bpoetry\s+install\b[^\n\r]*",
            r"\bpipenv\s+install\b[^\n\r]*",
        ]
        for pattern in explicit_patterns:
            match = re.search(pattern, desc, re.IGNORECASE)
            if match:
                cmd = match.group(0).strip()
                cmd = re.split(r"\s+(?:in|within|inside|under)\s+", cmd, maxsplit=1, flags=re.IGNORECASE)[0]
                cmd = cmd.rstrip(".,;")
                break

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

                    detected = detect_test_command(root)
                    if detected:
                        cmd = detected
                    else:
                        inferred = self._infer_test_command_from_files(root)
                        if inferred:
                            cmd = inferred
                        else:
                            cmd = ["python", "-c", "print('REV_NO_TEST_RUNNER')"]

        workdir = self._extract_workdir_hint(desc)
        cmd = self._apply_workdir(cmd, workdir)
        cmd = self._maybe_target_test_command(cmd, task, context) if isinstance(cmd, str) else cmd

        blocked = self._block_non_terminating_command("run_cmd", {"cmd": cmd}, task, context)
        if blocked:
            return blocked

        print(f"  [i] Using fallback heuristic: {cmd}")
        try:
            log_event = {
                "action": "fallback_heuristic_used",
                "task_id": task.task_id,
                "cmd": cmd,
            }
            print(f"  [log] {json.dumps(log_event, ensure_ascii=False)}")
        except Exception:
            pass
        raw_result = execute_tool("run_cmd", {"cmd": cmd}, agent_name="test_executor")
        return build_subagent_output(
            agent_name="TestExecutorAgent",
            tool_name="run_cmd",
            tool_args={"cmd": cmd},
            tool_output=raw_result,
            context=context,
            task_id=task.task_id,
        )

    @staticmethod
    def _extract_explicit_command(desc: str) -> Optional[str]:
        if not desc:
            return None
        candidates = []
        for pattern in (r"`([^`]+)`", r"\"([^\"]+)\"", r"'([^']+)'"):
            for match in re.findall(pattern, desc):
                if match and match.strip():
                    candidates.append(match.strip())
        command_tokens = (
            "npx", "npm", "yarn", "pnpm",
            "pip", "python", "python3",
            "node", "go", "cargo", "dotnet",
            "mvn", "gradle", "java",
            "pwsh", "powershell", "bash", "sh",
            "vitest", "jest", "pytest", "ava", "mocha", "playwright", "cypress",
        )
        token_pattern = r"\b(" + "|".join(command_tokens) + r")\b"
        token_match = re.search(token_pattern, desc, re.IGNORECASE)
        command_candidates = []
        for candidate in candidates:
            cleaned = candidate.strip().rstrip(".;:")
            if re.match(token_pattern, cleaned, re.IGNORECASE):
                command_candidates.append(cleaned)
        if command_candidates:
            return max(command_candidates, key=len)

        if token_match:
            candidate = desc[token_match.start():].strip()
            candidate = re.split(r"\s+(?:to|for|on|in|within|inside|under)\s+", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
            candidate = candidate.strip().rstrip(".;:")
            if re.match(token_pattern, candidate, re.IGNORECASE):
                return candidate
        return None

    @staticmethod
    def _extract_test_path_from_description(desc: str) -> Optional[str]:
        if not desc:
            return None
        match = re.search(r"([A-Za-z0-9_/\\.-]+\.(?:test|spec)\.[A-Za-z0-9]+)", desc)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _description_requests_full_suite(desc_lower: str) -> bool:
        tokens = (
            "run all tests",
            "all tests",
            "full suite",
            "full test suite",
            "entire suite",
            "entire test suite",
        )
        return any(token in desc_lower for token in tokens)

    @staticmethod
    def _command_has_test_path(cmd: str) -> bool:
        if not cmd:
            return False
        return bool(re.search(r"(?:test|spec)\.[A-Za-z0-9]+", cmd))

    @staticmethod
    def _find_default_test_path(context: RevContext) -> Optional[str]:
        """Find a default test file to target when none is specified."""
        root = Path(getattr(context, "workspace_root", "") or Path.cwd())
        try:
            discovered = quick_verify._discover_test_files(root, limit=3)  # type: ignore[attr-defined]
        except Exception:
            discovered = []
        if not discovered:
            return None
        # Prefer TS/JS tests
        preferred = sorted(
            discovered,
            key=lambda p: (0 if str(p).lower().endswith(".ts") else 1, len(str(p))),
        )
        return str(preferred[0])

    def _maybe_target_test_command(self, cmd: str, task: Task, context: RevContext) -> str:
        if not cmd or not isinstance(cmd, str):
            return cmd
        desc_lower = (task.description or "").lower()
        if self._description_requests_full_suite(desc_lower):
            return cmd
        if self._command_has_test_path(cmd):
            return cmd

        target_path = self._extract_test_path_from_description(task.description or "")
        if not target_path:
            target_path = context.get_agent_state("last_failing_test_file", "")
        if not target_path:
            target_path = self._find_default_test_path(context) or ""
        if not target_path:
            return cmd

        cmd_lower = cmd.lower()
        if "vitest" in cmd_lower and "run" in cmd_lower:
            return f"{cmd} {target_path}"
        if "pytest" in cmd_lower:
            return f"{cmd} {target_path}"
        if "jest" in cmd_lower and "--runtestsbypath" not in cmd_lower:
            return f"{cmd} --runTestsByPath {target_path}"
        return cmd

    def _execute_explicit_command(self, task: Task, context: RevContext, cmd: str) -> str:
        cmd = self._maybe_target_test_command(cmd, task, context)
        workdir = self._extract_workdir_hint(task.description or "")
        cmd = self._apply_workdir(cmd, workdir)
        blocked = self._block_non_terminating_command("run_cmd", {"cmd": cmd}, task, context)
        if blocked:
            return blocked
        print(f"  [i] Using explicit command from task: {cmd}")
        raw_result = execute_tool("run_cmd", {"cmd": cmd}, agent_name="test_executor")
        return build_subagent_output(
            agent_name="TestExecutorAgent",
            tool_name="run_cmd",
            tool_args={"cmd": cmd},
            tool_output=raw_result,
            context=context,
            task_id=task.task_id,
        )

    def _infer_test_command_from_files(self, root: Path) -> Optional[str | list[str]]:
        try:
            test_paths = quick_verify._discover_test_files(root, limit=3)  # type: ignore[attr-defined]
        except Exception:
            test_paths = []

        if not test_paths:
            return None

        first = Path(test_paths[0])
        suffix = first.suffix.lower()
        if suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            return ["npx", "vitest", "run", str(first)]
        if suffix == ".py":
            return ["pytest", "-q", str(first)]
        if suffix == ".go":
            return ["go", "test", str(first)]
        if suffix == ".rs":
            return ["cargo", "test", str(first)]
        if suffix == ".cs":
            return ["dotnet", "test", str(first)]
        return None

    def _extract_workdir_hint(self, desc: str) -> Optional[str]:
        """Best-effort guess for a working directory hinted in task text."""
        if config.WORKSPACE_ROOT_ONLY:
            return None
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
            if re.search(rf"(?:^|\s){known}(?:$|\s|[.,;:\)\]])", desc, re.IGNORECASE):
                return known
        return None

    def _apply_workdir(self, cmd: str | list[str], workdir: Optional[str]) -> str | list[str]:
        """Inject a working directory flag for supported package managers."""
        if not workdir:
            return cmd
        if isinstance(cmd, list):
            if any(token in ("--prefix", "--cwd", "--dir", "-C") for token in cmd):
                return cmd
        else:
            if re.search(r"\b(--prefix|--cwd|--dir|-C)\b", cmd):
                return cmd
        workdir_arg = workdir
        if " " in workdir_arg or "\t" in workdir_arg:
            workdir_arg = f"\"{workdir_arg}\""
        if isinstance(cmd, list):
            if cmd and cmd[0] == "npm":
                return ["npm", "--prefix", workdir_arg] + cmd[1:]
            if cmd and cmd[0] == "yarn":
                return ["yarn", "--cwd", workdir_arg] + cmd[1:]
            if cmd and cmd[0] == "pnpm":
                return ["pnpm", "--dir", workdir_arg] + cmd[1:]
            return cmd
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

        cmd_text = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        cmd_lower = cmd_text.lower().strip()
        desc = (task.description or "")
        desc_lower = desc.lower()

        vitest_correction = self._maybe_correct_vitest_command(cmd_text, task, context)
        if vitest_correction:
            return vitest_correction

        command_tokens = (
            "npx", "npm", "yarn", "pnpm",
            "pip", "python", "python3",
            "node", "go", "cargo", "dotnet",
            "mvn", "gradle", "java",
            "pwsh", "powershell", "bash", "sh",
            "vitest", "jest", "pytest", "ava", "mocha", "playwright", "cypress",
        )
        token_pattern = r"^(" + "|".join(command_tokens) + r")\b"

        if cmd_lower and not re.match(token_pattern, cmd_lower, re.IGNORECASE):
            test_path = self._extract_test_path(cmd_text)
            if test_path:
                if "vitest" in desc_lower:
                    return f"npx vitest run {test_path}"
                if "jest" in desc_lower:
                    return f"npx jest --runTestsByPath {test_path}"
                if "pytest" in desc_lower:
                    return f"pytest {test_path} -v"
                if "playwright" in desc_lower:
                    return f"npx playwright test {test_path}"
                if "cypress" in desc_lower:
                    return f"npx cypress run --spec {test_path}"
                return f"npm test -- {test_path}"

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

            detected = detect_test_command(root)
            if detected:
                return " ".join(detected)
            if (root / "yarn.lock").exists():
                return "yarn test"
            if (root / "pnpm-lock.yaml").exists():
                return "pnpm test"
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
                    detected = detect_test_command(root)
                    if detected:
                        return " ".join(detected)
                    return "npm test"

        # No correction needed
        return cmd_text

    def _maybe_correct_vitest_command(self, cmd_text: str, task: Task, context: RevContext) -> Optional[str]:
        if not cmd_text:
            return None
        try:
            tokens = shlex.split(cmd_text)
        except ValueError:
            tokens = cmd_text.split()
        if not tokens:
            return None

        tokens_lower = [t.lower() for t in tokens]
        vitest_idx = None
        for idx, tok in enumerate(tokens_lower):
            if tok.endswith("vitest") or tok.endswith("vitest.cmd"):
                vitest_idx = idx
                break

        def _has_non_watch_flags() -> bool:
            has_run_flag = any(tok == "--run" or tok.startswith("--run=") for tok in tokens_lower)
            has_run_subcommand = False
            if vitest_idx is not None:
                has_run_subcommand = any(tok == "run" for tok in tokens_lower[vitest_idx + 1 : vitest_idx + 3])
            watch_disabled = any(tok in ("--watch=false", "--watch=0") for tok in tokens_lower)
            if not watch_disabled and "--watch" in tokens_lower:
                for idx, tok in enumerate(tokens_lower):
                    if tok == "--watch" and idx + 1 < len(tokens_lower):
                        if tokens_lower[idx + 1] in ("false", "0", "no"):
                            watch_disabled = True
                            break
            return has_run_flag or has_run_subcommand or watch_disabled

        if vitest_idx is not None and _has_non_watch_flags():
            return None

        test_path = self._extract_test_path(cmd_text) or self._extract_test_path(task.description or "")
        if vitest_idx is not None:
            if test_path:
                return f"npx vitest run {test_path}"
            return "npx vitest run"

        package_manager = tokens_lower[0]
        if package_manager not in ("npm", "yarn", "pnpm"):
            return None

        script_name = None
        if len(tokens_lower) > 1 and tokens_lower[1] == "test":
            script_name = "test"
        elif len(tokens_lower) > 2 and tokens_lower[1] == "run":
            script_name = tokens_lower[2]

        if not script_name:
            return None

        desc_lower = (task.description or "").lower()
        # If we have a test path, prefer a direct Vitest run to avoid npm script flags like --runTestsByPath.
        if script_name == "test":
            if test_path:
                return f"npx vitest run {test_path}"
            return "npx vitest run"

        if "vitest" not in desc_lower:
            return None

        if test_path:
            return f"npx vitest run {test_path}"
        return "npx vitest run"
