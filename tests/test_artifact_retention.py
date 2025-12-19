import os
from pathlib import Path

from rev import config
from rev.execution.artifacts import write_tool_output_artifact


def _reset_env(key: str, original: str | None):
    if original is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = original


def test_tool_output_retention_limits_total_count():
    # Limit to 3 artifacts; older ones should be pruned.
    original = os.getenv("REV_TOOL_OUTPUTS_MAX_KEEP")
    os.environ["REV_TOOL_OUTPUTS_MAX_KEEP"] = "3"

    root = Path("tmp_test/manual").resolve() / "artifact_retention_total"
    root.mkdir(parents=True, exist_ok=True)
    config.set_workspace_root(root)

    for i in range(5):
        write_tool_output_artifact(
            tool="dummy",
            args={"i": i},
            output=f"out-{i}",
            session_id=None,
            task_id=f"t{i}",
        )

    files = list((config.TOOL_OUTPUTS_DIR).glob("*.json"))
    assert len(files) == 3

    _reset_env("REV_TOOL_OUTPUTS_MAX_KEEP", original)


def test_tool_output_retention_preserves_current_session():
    original = os.getenv("REV_TOOL_OUTPUTS_MAX_KEEP")
    os.environ["REV_TOOL_OUTPUTS_MAX_KEEP"] = "2"

    root = Path("tmp_test/manual").resolve() / "artifact_retention_session"
    root.mkdir(parents=True, exist_ok=True)
    config.set_workspace_root(root)

    # Older session artifacts (should prune beyond 2)
    for i in range(4):
        write_tool_output_artifact(
            tool="dummy",
            args={"i": i},
            output=f"old-{i}",
            session_id="sess-old",
            task_id=f"old-{i}",
        )

    # Current session artifacts should always be kept
    for i in range(3):
        write_tool_output_artifact(
            tool="dummy",
            args={"i": i},
            output=f"curr-{i}",
            session_id="sess-current",
            task_id=f"curr-{i}",
        )

    from rev.execution.artifacts import _prune_old_tool_outputs

    _prune_old_tool_outputs(2, keep_sessions={"sess-current"})

    files = list((config.TOOL_OUTPUTS_DIR).glob("*.json"))
    # At most max_keep artifacts are retained, but at least one from current session is preserved.
    assert len(files) == 2
    names = [p.name for p in files]
    assert any("sess-current" in n for n in names)
    assert sum("sess-old" in n for n in names) <= 1

    _reset_env("REV_TOOL_OUTPUTS_MAX_KEEP", original)
