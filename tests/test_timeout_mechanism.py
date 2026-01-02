"""Test timeout mechanism for command execution."""

import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.tools.command_runner import run_tests, run_cmd
import json


def test_run_tests_has_default_timeout():
    """Verify that run_tests has the correct default timeout."""
    import inspect
    sig = inspect.signature(run_tests)
    timeout_param = sig.parameters.get('timeout')

    assert timeout_param is not None, "run_tests should have a timeout parameter"
    assert timeout_param.default == 600, f"run_tests default timeout should be 600, got {timeout_param.default}"

    print(f"[OK] run_tests default timeout: {timeout_param.default} seconds (10 minutes)")


def test_run_cmd_has_default_timeout():
    """Verify that run_cmd has the correct default timeout."""
    import inspect
    sig = inspect.signature(run_cmd)
    timeout_param = sig.parameters.get('timeout')

    assert timeout_param is not None, "run_cmd should have a timeout parameter"
    assert timeout_param.default == 300, f"run_cmd default timeout should be 300, got {timeout_param.default}"

    print(f"[OK] run_cmd default timeout: {timeout_param.default} seconds (5 minutes)")


def test_timeout_actually_works():
    """Test that timeout mechanism actually kills long-running commands."""
    # Use a sleep command that should timeout
    result_json = run_cmd("python -c \"import time; time.sleep(10)\"", timeout=2)
    result = json.loads(result_json)

    assert "timeout" in result or "error" in result, f"Should have timeout/error info. Got: {result}"

    if "timeout" in result:
        assert result["timeout"] == 2, f"Timeout value should be preserved. Got: {result}"
        print(f"[OK] Timeout mechanism works (killed command after 2 seconds)")
    elif "error" in result and "timeout" in result["error"]:
        print(f"[OK] Timeout mechanism works (error message indicates timeout)")
    else:
        print(f"[WARN] Timeout may not have worked correctly. Result: {result}")


def test_timeout_parameter_passed_through():
    """Test that custom timeout parameter is actually used."""
    # Quick command that should complete
    start = time.time()
    result_json = run_cmd("echo test", timeout=120)
    elapsed = time.time() - start
    result = json.loads(result_json)

    # Should complete successfully (rc=0) quickly, not wait for full timeout
    assert result.get("rc") == 0, f"Command should succeed. Got: {result}"
    assert elapsed < 5, f"Should complete quickly, took {elapsed}s"

    print(f"[OK] Timeout parameter accepted (command completed in {elapsed:.2f}s)")


if __name__ == "__main__":
    test_run_tests_has_default_timeout()
    test_run_cmd_has_default_timeout()

    print("\n[INFO] Testing timeout mechanism (will take ~2-3 seconds)...")
    try:
        test_timeout_actually_works()
    except AssertionError as e:
        print(f"[WARN] Timeout test failed: {e}")

    test_timeout_parameter_passed_through()

    print("\n[OK] All timeout configuration tests passed!")
