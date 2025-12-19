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


def test_rewrite_python_keyword_args_renames_for_specific_callee():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"kw_args_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text(
            "def foo(**kwargs):\n"
            "    return kwargs\n"
            "\n"
            "def bar(**kwargs):\n"
            "    return kwargs\n"
            "\n"
            "x = foo(old=1, keep=2)\n"
            "y = bar(old=3)\n",
            encoding="utf-8",
        )

        result = json.loads(
            rev.rewrite_python_keyword_args(
                "main.py",
                callee="foo",
                renames=[{"old": "old", "new": "new"}],
            )
        )

        if not _libcst_available():
            assert "error" in result
            assert "libcst is not available" in result["error"]
            return

        assert "error" not in result
        assert result.get("changed") == 1
        new_text = p.read_text(encoding="utf-8")
        assert "foo(new=1, keep=2)" in new_text
        assert "bar(old=3)" in new_text
    finally:
        config.set_workspace_root(old_root)


def test_rename_imported_symbols_updates_import_and_references():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"rename_imported_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text(
            "from pkg.mod import Old\n"
            "from pkg.mod import Aliased as Local\n"
            "\n"
            "Old()\n"
            "Local()\n",
            encoding="utf-8",
        )

        result = json.loads(
            rev.rename_imported_symbols(
                "main.py",
                renames=[{"from_module": "pkg.mod", "old_name": "Old", "new_name": "New"}],
            )
        )

        if not _libcst_available():
            assert "error" in result
            assert "libcst is not available" in result["error"]
            return

        assert "error" not in result
        new_text = p.read_text(encoding="utf-8")
        assert "from pkg.mod import New" in new_text
        assert "New()" in new_text
        # Aliased import should keep local usage; import source may change only if matched
        assert "from pkg.mod import Aliased as Local" in new_text
        assert "Local()" in new_text
    finally:
        config.set_workspace_root(old_root)


def test_move_imported_symbols_splits_import_from_statement():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"move_imported_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text(
            "from old.mod import (\n"
            "    A,\n"
            "    B,\n"
            ")\n"
            "\n"
            "A(); B()\n",
            encoding="utf-8",
        )

        result = json.loads(
            rev.move_imported_symbols(
                "main.py",
                old_module="old.mod",
                new_module="new.mod",
                symbols=["A"],
            )
        )

        if not _libcst_available():
            assert "error" in result
            assert "libcst is not available" in result["error"]
            return

        assert "error" not in result
        assert result.get("changed") == 1
        new_text = p.read_text(encoding="utf-8")
        assert "from old.mod import" in new_text
        assert "from new.mod import" in new_text
        assert "A(); B()" in new_text
    finally:
        config.set_workspace_root(old_root)


def test_rewrite_python_function_parameters_rename_add_remove():
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / f"fn_params_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)

    old_root = config.ROOT
    try:
        config.set_workspace_root(root)
        p = root / "main.py"
        p.write_text(
            "def foo(a, old=None):\n"
            "    return a\n"
            "\n"
            "foo(a=1, old=2)\n",
            encoding="utf-8",
        )

        result = json.loads(
            rev.rewrite_python_function_parameters(
                "main.py",
                function="foo",
                rename=[{"old": "old", "new": "new"}],
                add=[{"name": "added", "default": "None"}],
                remove=["new"],
            )
        )

        if not _libcst_available():
            assert "error" in result
            assert "libcst is not available" in result["error"]
            return

        assert "error" not in result
        new_text = p.read_text(encoding="utf-8")
        assert "def foo(a, added=None)" in new_text or "def foo(a, added = None)" in new_text
        # Call should have had renamed keyword removed (remove=["new"]).
        assert "foo(a=1)" in new_text
    finally:
        config.set_workspace_root(old_root)
