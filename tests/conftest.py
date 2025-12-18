collect_ignore = ["tests/terminal/test_history.py"]

# CI/sandbox friendliness on Windows: ensure Python's tempfile uses a writable
# location inside the repo instead of a locked-down system temp directory.
#
# Many tests use `tempfile.TemporaryDirectory()` directly, which ignores
# pytest's `tmp_path` and can fail under restricted execution environments.
import os
import tempfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_TMP = _REPO_ROOT / ".pytest_tmp"
_TEST_TMP.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("TMP", str(_TEST_TMP))
os.environ.setdefault("TEMP", str(_TEST_TMP))
os.environ.setdefault("TMPDIR", str(_TEST_TMP))
tempfile.tempdir = str(_TEST_TMP)
