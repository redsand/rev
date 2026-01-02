"""Timeout recovery and diagnosis utilities."""

import json
import re
from typing import Dict, Any, Optional, Tuple


def analyze_timeout_output(result: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
    """Analyze timeout result to detect common issues and suggest fixes.

    Args:
        result: Command result dictionary with timeout, stdout, stderr

    Returns:
        Tuple of (is_watch_mode, diagnosis, suggested_fix)
    """
    if not isinstance(result, dict):
        return False, None, None

    # Check if this is a timeout
    if not result.get("timeout") and "timeout" not in str(result.get("error", "")).lower():
        return False, None, None

    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    combined = f"{stdout}\n{stderr}".lower()

    # Detect watch mode indicators
    watch_indicators = [
        "watch mode",
        "watching for file changes",
        "watching for changes",
        "press h for help",
        "press q to quit",
        "waiting for file changes",
        "file watcher",
        "jest --watch",
        "vitest watch",
    ]

    is_watch_mode = any(indicator in combined for indicator in watch_indicators)

    # Detect hanging server/process
    server_indicators = [
        "server listening",
        "listening on port",
        "server started",
        "application started",
        "started on port",
    ]

    has_hanging_server = any(indicator in combined for indicator in server_indicators)

    # Build diagnosis
    diagnosis = None
    suggested_fix = None

    if is_watch_mode:
        diagnosis = "Test command is running in watch mode and waiting for file changes (non-terminating)"

        # Suggest fix based on detected test framework
        if "vitest" in combined:
            suggested_fix = "Add '--run' flag to vitest command or update package.json test script to use 'vitest run' instead of 'vitest'"
        elif "jest" in combined:
            suggested_fix = "Add '--no-watch' or '--watchAll=false' to jest command"
        else:
            suggested_fix = "Configure test command to run in CI mode (non-interactive, no watch mode)"

    elif has_hanging_server:
        diagnosis = "Test started a server/application that didn't shut down (keeps process alive)"
        suggested_fix = "Ensure tests properly close servers in afterAll/afterEach hooks, or use --forceExit flag"

    elif "press" in combined or "waiting" in combined:
        diagnosis = "Command is waiting for user input or interaction (non-terminating)"
        suggested_fix = "Use non-interactive flags or ensure command runs in CI/batch mode"

    return is_watch_mode or has_hanging_server, diagnosis, suggested_fix


def enhance_timeout_error(result: Dict[str, Any]) -> Dict[str, Any]:
    """Enhance timeout error with diagnostic information.

    Args:
        result: Command result dictionary

    Returns:
        Enhanced result with diagnosis and suggestions
    """
    is_problematic, diagnosis, suggested_fix = analyze_timeout_output(result)

    if not is_problematic:
        return result

    # Enhance the error message
    enhanced = result.copy()

    error_parts = [enhanced.get("error", "command exceeded timeout")]

    if diagnosis:
        error_parts.append(f"\nDiagnosis: {diagnosis}")

    if suggested_fix:
        error_parts.append(f"\nSuggested fix: {suggested_fix}")

    enhanced["error"] = "\n".join(error_parts)
    enhanced["timeout_diagnosis"] = {
        "is_watch_mode": is_problematic,
        "diagnosis": diagnosis,
        "suggested_fix": suggested_fix,
    }

    return enhanced


def extract_package_json_test_script(package_json_content: str) -> Optional[str]:
    """Extract test script from package.json content.

    Args:
        package_json_content: Contents of package.json file

    Returns:
        Test script command or None
    """
    try:
        data = json.loads(package_json_content)
        scripts = data.get("scripts", {})
        return scripts.get("test")
    except (json.JSONDecodeError, KeyError):
        return None


def suggest_package_json_fix(test_script: str) -> Optional[str]:
    """Suggest a fix for package.json test script if it's in watch mode.

    Args:
        test_script: The current test script command

    Returns:
        Suggested replacement script or None
    """
    if not test_script:
        return None

    script_lower = test_script.lower()

    # Vitest fixes
    if "vitest" in script_lower:
        if "run" not in script_lower and "--run" not in script_lower:
            # Replace 'vitest' with 'vitest run'
            return re.sub(r'\bvitest\b', 'vitest run', test_script, count=1)

    # Jest fixes
    if "jest" in script_lower:
        if "--no-watch" not in script_lower and "--watchall=false" not in script_lower:
            return f"{test_script} --no-watch"

    return None
