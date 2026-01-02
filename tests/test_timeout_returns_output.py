"""Test that timeout returns partial output for diagnosis."""

import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.tools.command_runner import run_command_safe


def test_timeout_returns_partial_output():
    """Verify that when a command times out, we get the partial stdout/stderr."""

    # Run a command that prints something then hangs
    # CRITICAL: Must flush stdout or Python buffers it and we lose it on kill
    cmd = [
        'python', '-c',
        'import sys; print("Test output before hang"); sys.stdout.flush(); import time; time.sleep(10)'
    ]

    result = run_command_safe(cmd, timeout=2)

    # Check that we got a timeout
    assert "timeout" in result, f"Should have timeout field. Got: {result}"
    assert result.get("rc") == -1, f"RC should be -1 for timed out command. Got: {result}"
    assert "error" in result and "timeout" in result["error"], f"Should have timeout error. Got: {result}"

    # CRITICAL: Check that we got the partial output
    assert "stdout" in result, f"Should have stdout field even after timeout. Got: {result}"
    assert "stderr" in result, f"Should have stderr field even after timeout. Got: {result}"

    stdout = result.get("stdout", "")
    assert "Test output before hang" in stdout, f"Should capture output printed before timeout. Got stdout: '{stdout}'"

    print(f"[OK] Timeout returns partial output:")
    print(f"     stdout: {stdout[:100]}")
    print(f"     stderr: {result.get('stderr', '')[:100]}")
    print(f"     error: {result.get('error')}")


def test_timeout_with_watch_mode_command():
    """Simulate a watch mode command that would hang forever."""

    # Simulate a watch mode test runner
    cmd = [
        'python', '-c',
        '''
import sys
print("Running tests...")
print("Watching for file changes...")
sys.stdout.flush()
import time
time.sleep(10)
'''
    ]

    result = run_command_safe(cmd, timeout=2)

    assert result.get("rc") == -1, "Should timeout"
    stdout = result.get("stdout", "")

    # LLM should be able to see "Watching for file changes" to diagnose watch mode
    assert "Watching" in stdout or "watching" in stdout.lower(), \
        f"Should capture watch mode indicator. Got: '{stdout}'"

    print(f"[OK] Can diagnose watch mode from timeout output:")
    print(f"     Output: {stdout[:200]}")


if __name__ == "__main__":
    print("[INFO] Testing timeout with output capture (will take ~4 seconds)...\n")

    try:
        test_timeout_returns_partial_output()
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)

    try:
        test_timeout_with_watch_mode_command()
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)

    print("\n[OK] All timeout output tests passed!")
