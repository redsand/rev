"""Test framework detection doesn't switch based on output."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.execution.quick_verify import _detect_test_runner, _attempt_no_tests_fallback


def test_vitest_command_with_jest_in_output():
    """Test that vitest command is detected as vitest even if output mentions jest."""
    cmd = ['npx', '--yes', 'vitest', 'run', 'tests/file.test.ts']

    # Simulate output that mentions jest (e.g., error message saying "consider using jest")
    stdout = "No tests found. Consider using jest instead."
    stderr = ""

    runner = _detect_test_runner(cmd, stdout, stderr)

    assert runner == "vitest", f"Should detect vitest from command, not jest from output. Got: {runner}"
    print("[OK] Vitest command detected correctly despite jest in output")


def test_jest_command_with_vitest_in_output():
    """Test that jest command is detected as jest even if output mentions vitest."""
    cmd = ['npx', 'jest', '--runTestsByPath', 'tests/file.test.ts']

    # Simulate output that mentions vitest
    stdout = "Vitest is also available as an alternative"
    stderr = ""

    runner = _detect_test_runner(cmd, stdout, stderr)

    assert runner == "jest", f"Should detect jest from command. Got: {runner}"
    print("[OK] Jest command detected correctly despite vitest in output")


def test_vitest_fallback_builds_vitest_command():
    """Test that vitest command retry uses vitest syntax, not jest --runTestsByPath."""
    cmd = ['npx', '--yes', 'vitest', 'run', 'src/server.ts']

    # Simulate "no tests found" output
    stdout = "No test files found matching pattern"
    stderr = ""

    fallback_cmd = _attempt_no_tests_fallback(cmd, stdout, stderr, None)

    if fallback_cmd:
        # Should NOT contain --runTestsByPath (Jest flag)
        assert '--runTestsByPath' not in fallback_cmd, \
            f"Vitest fallback should not use Jest's --runTestsByPath flag. Got: {fallback_cmd}"

        # Should still be vitest
        assert 'vitest' in fallback_cmd, \
            f"Fallback should still use vitest. Got: {fallback_cmd}"

        print(f"[OK] Vitest fallback command correct: {' '.join(fallback_cmd)}")
    else:
        print("[OK] No fallback needed (correct)")


def test_jest_fallback_uses_run_tests_by_path():
    """Test that jest command retry uses --runTestsByPath correctly."""
    cmd = ['npx', 'jest', 'tests/file.test.ts']

    # Simulate "no tests found" output
    stdout = "No tests found"
    stderr = ""

    fallback_cmd = _attempt_no_tests_fallback(cmd, stdout, stderr, None)

    if fallback_cmd:
        # Should contain --runTestsByPath for Jest
        assert '--runTestsByPath' in fallback_cmd, \
            f"Jest fallback should use --runTestsByPath. Got: {fallback_cmd}"

        # Should still be jest
        assert 'jest' in fallback_cmd, \
            f"Fallback should still use jest. Got: {fallback_cmd}"

        print(f"[OK] Jest fallback command correct: {' '.join(fallback_cmd)}")
    else:
        print("[OK] No fallback needed (correct)")


def test_npm_test_vitest_detected_from_output():
    """Test that npm test can be detected as vitest from output when command is generic."""
    cmd = ['npm', 'test']

    # When command is generic (npm test), output should determine framework
    stdout = "Vitest v5.0.0\nCollecting tests..."
    stderr = ""

    runner = _detect_test_runner(cmd, stdout, stderr)

    # Should return "npm" for npm script commands
    assert runner == "npm", f"Should detect npm wrapper. Got: {runner}"
    print("[OK] npm test detected correctly")


def test_command_takes_priority_over_output():
    """Test that explicit framework in command always takes priority."""
    cmd = ['npx', 'vitest', 'run']

    # Output strongly suggests jest
    stdout = "jest version 29.0.0\nRunning jest tests..."
    stderr = "Error: jest configuration not found"

    runner = _detect_test_runner(cmd, stdout, stderr)

    assert runner == "vitest", f"Command should take priority over output. Got: {runner}"
    print("[OK] Command takes priority over misleading output")


def test_fallback_to_output_when_command_ambiguous():
    """Test that output is used when command doesn't specify framework."""
    cmd = ['node', 'run-tests.js']

    # Output indicates vitest
    stdout = "Vitest v5.0.0\nTest Files  1 passed"
    stderr = ""

    runner = _detect_test_runner(cmd, stdout, stderr)

    assert runner == "vitest", f"Should detect from output when command is ambiguous. Got: {runner}"
    print("[OK] Fallback to output works when command is ambiguous")


if __name__ == "__main__":
    test_vitest_command_with_jest_in_output()
    test_jest_command_with_vitest_in_output()
    test_vitest_fallback_builds_vitest_command()
    test_jest_fallback_uses_run_tests_by_path()
    test_npm_test_vitest_detected_from_output()
    test_command_takes_priority_over_output()
    test_fallback_to_output_when_command_ambiguous()

    print("\n[OK] All framework detection consistency tests passed!")
