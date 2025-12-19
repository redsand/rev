import json
import uuid
from pathlib import Path

import rev
from rev import config


def _libcst_available() -> bool:
    try:
        import libcst  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def test_rewrite_python_imports_prefix_rewrites_imports_and_preserves_syntax():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"rewrite_imports_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text(
            "import analysts  # c1\n"
            "import analysts.foo as foo\n"
            "from analysts import A, B as Bee  # c2\n"
            "from analysts.foo import Bar\n"
            "from other import X\n",
            encoding="utf-8",
        )

        result = json.loads(
            rev.rewrite_python_imports(
                "main.py",
                rules=[{"from_module": "analysts", "to_module": "lib.analysts", "match": "prefix"}],
            )
        )
        assert "error" not in result
        assert result.get("engine") in {"ast", "libcst"}
        assert result.get("changed", 0) >= 1

        new_text = p.read_text(encoding="utf-8")
        assert "import lib.analysts  # c1" in new_text
        assert "import lib.analysts.foo as foo" in new_text
        assert "from lib.analysts import A, B as Bee  # c2" in new_text
        assert "from lib.analysts.foo import Bar" in new_text
        assert "from other import X" in new_text
    finally:
        config.set_workspace_root(old_root)


def test_rewrite_python_imports_dry_run_does_not_write():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"rewrite_imports_dry_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        original = "import analysts\n"
        p.write_text(original, encoding="utf-8")

        result = json.loads(
            rev.rewrite_python_imports(
                "main.py",
                rules=[{"from_module": "analysts", "to_module": "lib.analysts", "match": "exact"}],
                dry_run=True,
            )
        )
        assert "error" not in result
        assert result.get("engine") in {"ast", "libcst"}
        assert result.get("dry_run") is True
        assert result.get("changed") == 1
        assert p.read_text(encoding="utf-8") == original
        assert "diff" in result
    finally:
        config.set_workspace_root(old_root)


def test_rewrite_python_imports_noop_returns_changed_0():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"rewrite_imports_noop_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text("from something_else import A\n", encoding="utf-8")

        result = json.loads(
            rev.rewrite_python_imports(
                "main.py",
                rules=[{"from_module": "analysts", "to_module": "lib.analysts", "match": "prefix"}],
            )
        )
        assert "error" not in result
        assert result.get("engine") in {"ast", "libcst"}
        assert result.get("changed") == 0
        assert p.read_text(encoding="utf-8") == "from something_else import A\n"
    finally:
        config.set_workspace_root(old_root)


def test_rewrite_python_imports_preserves_multiline_imports_with_libcst_when_available():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"rewrite_imports_multiline_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        original = (
            "from analysts import (\n"
            "    A,\n"
            "    B,  # trailing\n"
            ")\n"
        )
        p.write_text(original, encoding="utf-8")

        result = json.loads(
            rev.rewrite_python_imports(
                "main.py",
                rules=[{"from_module": "analysts", "to_module": "lib.analysts", "match": "exact"}],
                engine="libcst" if _libcst_available() else "auto",
            )
        )
        if not _libcst_available():
            assert "error" not in result
            assert result.get("engine") == "ast"
            new_text = p.read_text(encoding="utf-8")
            assert "from lib.analysts import" in new_text
            return

        assert "error" not in result
        assert result.get("engine") in {"ast", "libcst"}
        assert result.get("changed") == 1

        new_text = p.read_text(encoding="utf-8")
        if result.get("engine") == "libcst":
            assert "from lib.analysts import (\n" in new_text
            assert "    B,  # trailing\n" in new_text
            assert ")\n" in new_text
        else:
            # AST fallback may collapse formatting; still require correctness and syntax.
            assert "from lib.analysts import" in new_text
    finally:
        config.set_workspace_root(old_root)
