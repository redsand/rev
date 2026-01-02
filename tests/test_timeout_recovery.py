"""Test timeout recovery and diagnosis."""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rev.execution.timeout_recovery import (
    analyze_timeout_output,
    enhance_timeout_error,
    suggest_package_json_fix
)


def test_detect_watch_mode_vitest():
    """Test detection of Vitest watch mode."""
    result = {
        "timeout": 600,
        "rc": -1,
        "stdout": "Vitest is running in watch mode\nWatching for file changes...\nPress h for help, q to quit",
        "stderr": "",
        "error": "command exceeded 600s timeout"
    }

    is_watch, diagnosis, fix = analyze_timeout_output(result)

    assert is_watch == True, "Should detect watch mode"
    assert "watch mode" in diagnosis.lower(), f"Diagnosis should mention watch mode: {diagnosis}"
    assert "--run" in fix or "vitest run" in fix, f"Fix should suggest --run flag: {fix}"

    print(f"[OK] Detected Vitest watch mode")
    print(f"     Diagnosis: {diagnosis}")
    print(f"     Fix: {fix}")


def test_detect_watch_mode_jest():
    """Test detection of Jest watch mode."""
    result = {
        "timeout": 600,
        "rc": -1,
        "stdout": "Jest watch mode\nWatch Usage\n Press p to filter by filename\n Press q to quit watch mode",
        "stderr": "",
        "error": "command exceeded 600s timeout"
    }

    is_watch, diagnosis, fix = analyze_timeout_output(result)

    assert is_watch == True, "Should detect watch mode"
    assert fix is not None, f"Should have a suggested fix"
    # Fix should mention either Jest-specific flags or general CI mode
    assert any(keyword in fix.lower() for keyword in ["jest", "--no-watch", "ci mode", "non-interactive"]), \
        f"Fix should suggest Jest flags or CI mode: {fix}"

    print(f"[OK] Detected Jest watch mode")
    print(f"     Fix: {fix}")


def test_detect_hanging_server():
    """Test detection of hanging server."""
    result = {
        "timeout": 300,
        "rc": -1,
        "stdout": "Server listening on port 3000\nTest suite started",
        "stderr": "",
        "error": "command exceeded 300s timeout"
    }

    is_problematic, diagnosis, fix = analyze_timeout_output(result)

    assert is_problematic == True, "Should detect hanging server"
    assert "server" in diagnosis.lower(), f"Diagnosis should mention server: {diagnosis}"
    assert "close" in fix.lower() or "shutdown" in fix.lower() or "forceexit" in fix.lower(), \
        f"Fix should suggest server cleanup: {fix}"

    print(f"[OK] Detected hanging server")
    print(f"     Diagnosis: {diagnosis}")


def test_enhance_timeout_error():
    """Test error enhancement with diagnosis."""
    result = {
        "timeout": 600,
        "rc": -1,
        "stdout": "Vitest watch mode\nWaiting for file changes...",
        "stderr": "",
        "error": "command exceeded 600s timeout"
    }

    enhanced = enhance_timeout_error(result)

    assert "Diagnosis:" in enhanced["error"], "Should add diagnosis"
    assert "Suggested fix:" in enhanced["error"], "Should add suggested fix"
    assert "timeout_diagnosis" in enhanced, "Should add diagnosis object"

    print(f"[OK] Enhanced error message")
    print(f"     Error: {enhanced['error'][:200]}")


def test_package_json_fix_vitest():
    """Test package.json fix suggestion for Vitest."""
    script = "vitest"
    fixed = suggest_package_json_fix(script)

    assert fixed == "vitest run", f"Should suggest 'vitest run', got: {fixed}"

    # Already has run
    script2 = "vitest run"
    fixed2 = suggest_package_json_fix(script2)
    assert fixed2 is None, "Should not suggest fix if already correct"

    print(f"[OK] Package.json fix for Vitest")


def test_package_json_fix_jest():
    """Test package.json fix suggestion for Jest."""
    script = "jest"
    fixed = suggest_package_json_fix(script)

    assert fixed == "jest --no-watch", f"Should add --no-watch, got: {fixed}"

    print(f"[OK] Package.json fix for Jest")


if __name__ == "__main__":
    test_detect_watch_mode_vitest()
    test_detect_watch_mode_jest()
    test_detect_hanging_server()
    test_enhance_timeout_error()
    test_package_json_fix_vitest()
    test_package_json_fix_jest()

    print("\n[OK] All timeout recovery tests passed!")
