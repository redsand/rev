from pathlib import Path

from rev import config
from rev.workspace import get_workspace


def _make_workspace() -> Path:
    base = Path("tmp_test/manual").resolve()
    base.mkdir(parents=True, exist_ok=True)
    root = base / "workspace_dedupe"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_workspace_resolve_path_dedupes_redundant_prefix():
    old_root = config.ROOT
    root = _make_workspace()
    try:
        config.set_workspace_root(root)
        (root / "lib" / "analysts").mkdir(parents=True, exist_ok=True)
        (root / "lib" / "analysts" / "__init__.py").write_text("# init\n", encoding="utf-8")

        ws = get_workspace()
        resolved = ws.resolve_path("lib/analysts/lib/analysts/__init__.py")

        assert resolved.abs_path == (root / "lib" / "analysts" / "__init__.py")
        # Ensure we did not create deeper nested directories during resolution
        assert not (root / "lib" / "analysts" / "lib").exists()
    finally:
        config.set_workspace_root(old_root)
