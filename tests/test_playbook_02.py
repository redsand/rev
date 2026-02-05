#!/usr/bin/env python3
import os
import sys
import shutil
import tempfile
from pathlib import Path

if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, 'strict')

os.environ["REV_LLM_PROVIDER"] = "ollama"
os.environ.setdefault("OLLAMA_MODEL", "glm-4.7:cloud")
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

print("Testing REV on playbook 02 (Advanced Shopping Cart)...")

# Use temporary directory for workspace
original_cwd = os.getcwd()
playbooks_dir = Path(original_cwd) / "playbooks" / "02_advanced_shopping_cart"
try:
    # Create temp directory manually to ignore cleanup errors on Windows
    tmpdir = Path(tempfile.mkdtemp())
    workspace = tmpdir / "workspace"
    workspace.mkdir()
    print(f"Workspace: {workspace}")

    # Copy test files and existing implementations to workspace
    for file in ["test_shopping_cart.py", "product.py", "cart.py", "exceptions.py"]:
        if (playbooks_dir / file).exists():
            shutil.copy(playbooks_dir / file, workspace / file)
            print(f"Copied {file} to workspace")

    # Change to the workspace directory so REV uses it as the root
    os.chdir(workspace)

    try:
        from rev.execution.orchestrator import run_orchestrated
        result = run_orchestrated(
            "Implement the shopping cart system with Product class, ShoppingCart class, and custom exceptions. Ensure all methods in product.py, cart.py, and exceptions.py are fully implemented with proper error handling, type hints, and thread-safety using locks.",
            project_root=workspace,
            enable_learning=False,
            enable_research=False,
            enable_review=False,
            enable_validation=True,
            enable_auto_fix=True,
            parallel_workers=1,
            auto_approve=True,
            read_only=False,
            enable_prompt_optimization=False,
            validation_retries=2,
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
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except:
        pass
