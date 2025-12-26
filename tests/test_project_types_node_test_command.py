from pathlib import Path
import uuid

from rev.tools.project_types import detect_test_command


def _make_root() -> Path:
    root = Path("tmp_test") / "project_types" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_detect_test_command_uses_test_script():
    root = _make_root()
    (root / "package.json").write_text(
        '{"name": "app", "scripts": {"test": "vitest run"}}',
        encoding="utf-8",
    )

    cmd = detect_test_command(root)
    assert cmd == ["npm", "test"]


def test_detect_test_command_prefers_ci_script():
    root = _make_root()
    (root / "package.json").write_text(
        '{"name": "app", "scripts": {"test": "echo \\"Error: no test specified\\" && exit 1", "test:ci": "vitest run"}}',
        encoding="utf-8",
    )
    (root / "yarn.lock").write_text("", encoding="utf-8")

    cmd = detect_test_command(root)
    assert cmd == ["yarn", "run", "test:ci"]


def test_detect_test_command_uses_runner_dependency():
    root = _make_root()
    (root / "package.json").write_text(
        '{"name": "app", "devDependencies": {"jest": "^29.0.0"}}',
        encoding="utf-8",
    )

    cmd = detect_test_command(root)
    assert cmd == ["npx", "--yes", "jest"]


def test_detect_test_command_returns_none_without_tests():
    root = _make_root()
    (root / "package.json").write_text('{"name": "app"}', encoding="utf-8")

    cmd = detect_test_command(root)
    assert cmd is None
