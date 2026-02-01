#!/usr/bin/env python3
import os
import sys
import shutil
import tempfile
import time
from pathlib import Path

if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, 'strict')

os.environ["REV_LLM_PROVIDER"] = "ollama"
os.environ.setdefault("OLLAMA_MODEL", "glm-4.7:cloud")
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

print("Testing REV on playbook 01...")

# Use temporary directory for workspace
original_cwd = os.getcwd()
playbooks_dir = Path(original_cwd) / "playbooks" / "01_simple_string_manipulation"
try:
    # Create temp directory manually to ignore cleanup errors on Windows
    tmpdir = Path(tempfile.mkdtemp())
    workspace = tmpdir / "workspace"
    workspace.mkdir()
    print(f"Workspace: {workspace}")

    # Copy test files to workspace for validation
    if (playbooks_dir / "test_string_utils.py").exists():
        shutil.copy(playbooks_dir / "test_string_utils.py", workspace / "test_string_utils.py")
        print(f"Copied test file to workspace")

    # Copy existing string_utils.py if it exists
    if (playbooks_dir / "string_utils.py").exists():
        shutil.copy(playbooks_dir / "string_utils.py", workspace / "string_utils.py")

    # Change to the workspace directory so REV uses it as the root
    os.chdir(workspace)

    try:
        from rev.execution.orchestrator import run_orchestrated
        result = run_orchestrated(
            "Implement string utility functions: reverse_string, count_vowels, is_palindrome, capitalize_words",
            project_root=workspace,
            enable_learning=False,
            enable_research=False,  # Disable research to focus on implementation
            enable_review=False,
            enable_validation=True,  # Enable validation to test it
            enable_auto_fix=True,  # Enable auto-fix for test failures
            parallel_workers=1,
            auto_approve=True,
            read_only=False,
            enable_prompt_optimization=False,  # Disable prompt optimization for automated testing
            validation_retries=2,  # Allow retries for fixing test failures
        )
        print(f"REV completed. Result preview: {str(result)[:200]}...")
        print(f"Success: {result.success}")
        print(f"Phase reached: {result.phase_reached}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
finally:
    os.chdir(original_cwd)
    # Clean up temp directory, ignore errors on Windows
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except:
        pass
