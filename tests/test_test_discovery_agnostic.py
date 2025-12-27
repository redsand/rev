from pathlib import Path

from rev.execution import quick_verify


def test_looks_like_test_file_extension_agnostic() -> None:
    path = Path("tests/e2e/login.test.feature")
    assert quick_verify._looks_like_test_file(path) is True


def test_path_is_test_like_for_spec_dir() -> None:
    path = Path("specs/login.feature")
    assert quick_verify._path_is_test_like(path) is True


def test_extract_test_paths_from_cmd_extension_agnostic() -> None:
    cmd_parts = ["runner", "tests/login.test.feature"]
    assert quick_verify._extract_test_paths_from_cmd(cmd_parts) == ["tests/login.test.feature"]
