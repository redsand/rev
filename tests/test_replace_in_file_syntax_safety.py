import json
import uuid
from pathlib import Path

import rev
from rev import config


def test_replace_in_file_rejects_python_syntax_error_and_does_not_write():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"syntax_safe_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    # Operate inside the rev workspace root so rev._safe_path permits edits.
    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text("x = 1\nprint(x)\n", encoding="utf-8")

        # Introduce a syntax error
        result = json.loads(rev.replace_in_file("main.py", "x = 1", "x ="))
        assert "error" in result
        assert "SyntaxError" in result["error"]

        # File should remain unchanged because we validate before writing.
        assert p.read_text(encoding="utf-8") == "x = 1\nprint(x)\n"
    finally:
        config.set_workspace_root(old_root)


def test_replace_in_file_allows_valid_python_edit():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"syntax_ok_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text("x = 1\nprint(x)\n", encoding="utf-8")

        result = json.loads(rev.replace_in_file("main.py", "x = 1", "x = 2"))
        assert result.get("replaced") == 1
        assert "error" not in result
        assert p.read_text(encoding="utf-8") == "x = 2\nprint(x)\n"
    finally:
        config.set_workspace_root(old_root)
