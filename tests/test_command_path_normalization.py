import shutil
import uuid
from pathlib import Path

import pytest

from rev.tools import command_runner


@pytest.fixture
def temp_root():
    root = Path("tmp_test").resolve() / f"cmd_path_norm_{uuid.uuid4().hex}"
    (root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (root / "configs").mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_normalize_command_args_absolute_to_relative(temp_root):
    file_path = temp_root / "tests" / "unit" / "sample_test.py"
    file_path.write_text("print('ok')")

    args = ["pytest", str(file_path)]
    normalized = command_runner._normalize_command_args(args, temp_root)

    assert len(normalized) == 2
    assert not Path(normalized[1]).is_absolute()
    assert Path(normalized[1]) == Path("tests") / "unit" / "sample_test.py"


def test_normalize_command_args_flag_value(temp_root):
    config_path = temp_root / "configs" / "app.toml"
    config_path.write_text("title = 'demo'")

    args = ["python", "--config=./configs\\app.toml"]
    normalized = command_runner._normalize_command_args(args, temp_root)

    assert len(normalized) == 2
    assert normalized[1].startswith("--config=")
    _, value = normalized[1].split("=", 1)
    assert not Path(value).is_absolute()
    assert Path(value) == Path("configs") / "app.toml"


def test_run_command_safe_reports_cwd(temp_root):
    result = command_runner.run_command_safe("echo hi && dir", cwd=temp_root)

    assert result.get("blocked") is True
    assert result.get("cwd") == str(temp_root.resolve())
