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
os.environ["OLLAMA_MODEL"] = "glm-4.7:cloud"
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

print("Testing REV on playbook 01...")

# Use temporary directory for workspace
original_cwd = os.getcwd()
try:
    # Create temp directory manually to ignore cleanup errors on Windows
    tmpdir = Path(tempfile.mkdtemp())
    workspace = tmpdir / "workspace"
    workspace.mkdir()
    print(f"Workspace: {workspace}")

    # Change to the workspace directory so REV uses it as the root
    os.chdir(workspace)

    try:
        from rev.execution.orchestrator import run_orchestrated
        result = run_orchestrated(
            "Implement string utility functions: reverse_string, count_vowels, is_palindrome, capitalize_words",
            project_root=workspace,
            enable_learning=False,
            enable_research=True,
            enable_review=False,
            enable_validation=False,
            parallel_workers=1,
            auto_approve=True,
            read_only=False,
            enable_prompt_optimization=False,  # Disable prompt optimization for automated testing
        )
        print(f"REV completed. Result preview: {str(result)[:200]}...")
        print(f"Success: {result.success}")
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
