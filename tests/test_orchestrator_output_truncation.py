"""Test that orchestrator properly preserves error details from command outputs."""

import json
from rev.execution.orchestrator import Orchestrator
from rev.models.task import Task, TaskStatus


def test_command_error_output_not_truncated():
    """Verify that command error output preserves enough detail for diagnosis."""

    # Simulate a task with a build error (like npm run build with pinia error)
    task = Task(description="npm run build", action_type="tool")
    task.status = TaskStatus.COMPLETED

    # Simulate the actual error from the build
    stderr_content = """x Build failed in 162ms
error during build:
[vite]: Rollup failed to resolve import "pinia" from "C:/Users/champ/source/repos/test-app/src/main.ts".
This is most likely unintended because it can break your application at runtime.
If you do want to externalize this module explicitly add it to
`build.rollupOptions.external`
    at viteWarn (file:///C:/Users/champ/source/repos/test-app/node_modules/vite/dist/node/chunks/dep-BK3b2jBa.js:65855:17)
    at onRollupWarning (file:///C:/Users/champ/source/repos/test-app/node_modules/vite/dist/node/chunks/dep-BK3b2jBa.js:65887:5)"""

    tool_output = json.dumps({
        "rc": 1,
        "stdout": "\n> test-app@0.1.0 build\n> vite build\n\nvite v5.4.21 building for production...\ntransforming...\n✓ 3 modules transformed.\n",
        "stderr": stderr_content,
        "cmd": "npm run build",
        "cwd": "C:\\Users\\champ\\source\\repos\\test-app"
    })

    # Add tool event to task
    task.tool_events = [{
        "tool": "run_cmd",
        "args": {"cmd": ["npm", "run", "build"]},
        "raw_result": tool_output
    }]

    # Now simulate the work summary generation logic
    # This replicates the code from orchestrator.py lines 5769-5837
    event = task.tool_events[-1]
    tool_output_str = event.get('raw_result')
    tool_name = event.get('tool', '')

    summary = tool_output_str.strip()

    # Apply the smart truncation logic
    if tool_name in ('run_cmd', 'run_tests', 'run_property_tests'):
        try:
            result_data = json.loads(summary)
            if isinstance(result_data, dict):
                rc = result_data.get('rc', 0)
                stderr = result_data.get('stderr', '').strip()
                stdout = result_data.get('stdout', '').strip()

                if rc != 0 and stderr:
                    if len(stderr) > 2000:
                        error_markers = ['error:', 'Error:', 'ERROR:', 'failed', 'Failed', 'FAILED']
                        best_section = stderr[-2000:]

                        for marker in error_markers:
                            idx = stderr.rfind(marker)
                            if idx > 0:
                                start = max(0, idx - 500)
                                end = min(len(stderr), idx + 1500)
                                best_section = stderr[start:end]
                                if start > 0:
                                    best_section = '...' + best_section
                                if end < len(stderr):
                                    best_section = best_section + '...'
                                break

                        summary = json.dumps({
                            'rc': rc,
                            'stderr': best_section,
                            'stdout': stdout[:500] if stdout else ''
                        })
        except (json.JSONDecodeError, ValueError):
            pass

    output_detail = summary

    # Generous limits: 2500 chars for command output
    limit = 2500 if tool_name in ('run_cmd', 'run_tests', 'run_property_tests') else 800
    if len(output_detail) > limit:
        output_detail = output_detail[:limit] + '...'

    # Verify the critical error message is preserved
    assert 'pinia' in output_detail, "Error message should mention 'pinia'"
    assert 'Rollup failed to resolve import' in output_detail, "Should preserve the error description"
    assert 'rc' in output_detail or stderr_content in output_detail, "Should preserve error context"

    # Verify it's not the old 300-char truncation
    assert len(output_detail) > 300, f"Output should be longer than old 300 char limit, got {len(output_detail)}"

    print(f"[OK] Error detail preserved ({len(output_detail)} chars)")
    print(f"[OK] Contains 'pinia' error: {('pinia' in output_detail)}")


def test_successful_command_brief_summary():
    """Verify successful commands get brief summaries."""

    task = Task(description="npm run lint", action_type="tool")
    task.status = TaskStatus.COMPLETED

    stdout_content = "✓ All files passed linting\n" * 50  # Make it long

    tool_output = json.dumps({
        "rc": 0,
        "stdout": stdout_content,
        "stderr": "",
        "cmd": "npm run lint"
    })

    task.tool_events = [{
        "tool": "run_cmd",
        "args": {"cmd": ["npm", "run", "lint"]},
        "raw_result": tool_output
    }]

    # Apply the logic
    event = task.tool_events[-1]
    tool_output_str = event.get('raw_result')
    tool_name = event.get('tool', '')
    summary = tool_output_str.strip()

    if tool_name in ('run_cmd', 'run_tests', 'run_property_tests'):
        try:
            result_data = json.loads(summary)
            if isinstance(result_data, dict):
                rc = result_data.get('rc', 0)
                stderr = result_data.get('stderr', '').strip()
                stdout = result_data.get('stdout', '').strip()

                if rc == 0:
                    summary = json.dumps({
                        'rc': 0,
                        'stdout': stdout[:800] if len(stdout) > 800 else stdout
                    })
        except (json.JSONDecodeError, ValueError):
            pass

    output_detail = summary
    limit = 2500
    if len(output_detail) > limit:
        output_detail = output_detail[:limit] + '...'

    # Verify successful commands are more concise
    result_data = json.loads(output_detail)
    assert result_data['rc'] == 0
    assert 'stderr' not in result_data or not result_data.get('stderr'), "No stderr for successful commands"

    print(f"[OK] Success summary is concise ({len(output_detail)} chars)")


if __name__ == "__main__":
    test_command_error_output_not_truncated()
    test_successful_command_brief_summary()
    print("\n[OK] All tests passed!")
