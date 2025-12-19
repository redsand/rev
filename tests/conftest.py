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
import shutil


_REPO_ROOT = Path(__file__).resolve().parents[1]

def _choose_temp_base() -> Path:
    """Pick a temp base directory that is reliably writable/listable on Windows."""
    candidates = [
        Path(tempfile.gettempdir()) / "rev_tmp_test",
        _REPO_ROOT / "tmp_test",
    ]
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / f"probe_{os.getpid()}_{uuid.uuid4().hex[:8]}"
            probe.mkdir(parents=True, exist_ok=True)
            # Ensure we can list and remove it (some environments create dirs with restrictive ACLs).
            list(probe.iterdir())
            shutil.rmtree(probe, ignore_errors=True)
            return base
        except Exception:
            continue
    # Last resort: system temp root
    return Path(tempfile.gettempdir())


_BASE_TMP = _choose_temp_base()
_TEST_TMP_BASE = _BASE_TMP / "temp"
_TEST_TMP_BASE.mkdir(parents=True, exist_ok=True)

# Avoid colliding with prior runs that may leave behind locked/ACL-protected dirs.
_TEST_TMP = _TEST_TMP_BASE / f"run_{os.getpid()}_{uuid.uuid4().hex[:8]}"
_TEST_TMP.mkdir(parents=True, exist_ok=True)

def _temp_root_is_usable(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f"probe_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        probe.mkdir(parents=True, exist_ok=True)
        list(probe.iterdir())
        shutil.rmtree(probe, ignore_errors=True)
        return True
    except Exception:
        return False


# Only override TEMP/TMP when the environment temp root is unusable.
# Some Windows security setups can create temp subdirectories that become
# unreadable (WinError 5) under custom temp roots, which breaks pytest's tmp_path.
# Force all temp usage for tests into the validated per-run temp directory to avoid
# Windows ACL/EDR issues with default %TEMP% paths.
os.environ["TMP"] = str(_TEST_TMP)
os.environ["TEMP"] = str(_TEST_TMP)
os.environ["TMPDIR"] = str(_TEST_TMP)
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
    """Optionally customize pytest basetemp.

    Historically this repo forced a per-run `basetemp` to avoid teardown issues
    on Windows (WinError 5). In some environments, however, creating or using a
    custom basetemp can itself trigger restrictive ACL behavior.

    Defaulting to pytest's own temp root has proven more reliable across a wider
    set of restricted Windows setups.
    """
    return
