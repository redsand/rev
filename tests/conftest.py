collect_ignore = ["tests/terminal/test_history.py"]

# CI/sandbox friendliness on Windows: ensure Python's tempfile uses a writable
# location inside the repo instead of a locked-down system temp directory.
#
# Many tests use `tempfile.TemporaryDirectory()` directly, which ignores
# pytest's `tmp_path` and can fail under restricted execution environments.
import os
import tempfile
from pathlib import Path
import uuid


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_TMP_BASE = _REPO_ROOT / "tmp_test" / "temp"
_TEST_TMP_BASE.mkdir(parents=True, exist_ok=True)
# Avoid colliding with prior runs that may leave behind locked/ACL-protected dirs.
_TEST_TMP = _TEST_TMP_BASE / f"run_{os.getpid()}_{uuid.uuid4().hex[:8]}"
_TEST_TMP.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TMP", str(_TEST_TMP))
os.environ.setdefault("TEMP", str(_TEST_TMP))
os.environ.setdefault("TMPDIR", str(_TEST_TMP))
tempfile.tempdir = str(_TEST_TMP)

# ---------------------------------------------------------------------------
# Pytest cleanup robustness (Windows restricted environments)
# ---------------------------------------------------------------------------
#
# Some Windows environments (CI/sandbox/EDR) can intermittently deny directory
# listings for pytest's temp root during teardown, which causes pytest to exit
# with a non-test error while tests themselves have already run.
#
# Make cleanup best-effort so test failures remain actionable.
try:  # pragma: no cover
    import _pytest.pathlib as _pytest_pathlib
    import _pytest.tmpdir as _pytest_tmpdir

    _orig_cleanup_dead_symlinks = _pytest_pathlib.cleanup_dead_symlinks

    def _safe_cleanup_dead_symlinks(root):  # type: ignore[override]
        try:
            return _orig_cleanup_dead_symlinks(root)
        except PermissionError:
            return None
        except OSError as e:
            # WinError 5: Access is denied
            if getattr(e, "winerror", None) == 5:
                return None
            raise

    _pytest_pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks  # type: ignore[assignment]
    # tmpdir plugin imports cleanup_dead_symlinks by name; patch there too.
    try:
        _pytest_tmpdir.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks  # type: ignore[assignment]
    except Exception:
        pass
except Exception:
    pass


def pytest_configure(config):  # pragma: no cover
    """Force a unique basetemp per run.

    Some Windows environments can end up with temp dirs that become undeletable
    (WinError 5). Using a unique basetemp per run avoids pytest trying to clean
    up/reuse a previously-problematic directory.
    """
    try:
        base = _REPO_ROOT / "tmp_test" / "basetemp_runs" / f"run_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        base.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(base)
    except Exception:
        return
