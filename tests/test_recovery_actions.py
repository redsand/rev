import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rev.execution import recovery


def test_placeholder_commands_are_skipped(monkeypatch):
    action = recovery.RecoveryAction(
        description="test",
        strategy=recovery.RecoveryStrategy.ROLLBACK,
        commands=["git revert <commit-hash>"],
        requires_approval=False,
    )

    # Capture logs
    logs = []

    class DummyLogger:
        def log(self, *args, **kwargs):
            logs.append((args, kwargs))

    monkeypatch.setattr(recovery, "get_logger", lambda: DummyLogger())

    result = recovery.apply_recovery_action(action, dry_run=False)

    assert result["success"] is False
    assert any("Placeholder command skipped" in err.get("error", "") for err in result["errors"])
    assert any("PLACEHOLDER_SKIPPED" in str(args[1]) for args, _ in logs)


def test_requires_approval_prompts_and_aborts_on_reject(monkeypatch):
    action = recovery.RecoveryAction(
        description="dangerous",
        strategy=recovery.RecoveryStrategy.ROLLBACK,
        commands=["git reset --hard HEAD"],
        requires_approval=True,
    )

    # Force rejection
    monkeypatch.setattr(recovery, "prompt_scary_operation", lambda *a, **k: False)

    logs = []

    class DummyLogger:
        def log(self, *args, **kwargs):
            logs.append((args, kwargs))

    monkeypatch.setattr(recovery, "get_logger", lambda: DummyLogger())

    result = recovery.apply_recovery_action(action, dry_run=False)

    assert result["success"] is False
    assert any("rejected" in err.get("error", "") for err in result["errors"])
    assert any("APPROVAL_REJECTED" in str(args[1]) for args, _ in logs)
