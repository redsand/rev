"""Interrupt handling behaviors for the main CLI entrypoint."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_keyboard_interrupt_triggers_resume_hint(monkeypatch, capsys):
    """Keyboard interrupts should invoke StateManager.on_interrupt to show resume info."""

    # Import inside the test to avoid import‑time side effects
    import rev.main as main

    calls = {
        "on_interrupt": False,
        "state_manager_created": False,
    }

    class DummyTask:
        def __init__(self):
            self.id = "1"
            self.description = "placeholder"

    class DummyPlan:
        """Minimal stand-in for ExecutionPlan."""

        def __init__(self):
            self.tasks = [DummyTask()]

        def get_summary(self):
            return "dummy plan"

    class DummyStateManager:
        def __init__(self, plan):  # pragma: no cover - trivial wiring
            calls["state_manager_created"] = isinstance(plan, DummyPlan)

        def on_interrupt(self):
            calls["on_interrupt"] = True
            print("rev --resume dummy_checkpoint")

    def raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    # Configure arguments and monkeypatch flow so execution enters the interrupt handler.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rev",
            "--no-orchestrate",
            "--no-review",
            "--no-validate",
            "--parallel",
            "1",
            "demo task",
        ],
    )
    monkeypatch.setattr(main, "StateManager", DummyStateManager)
    monkeypatch.setattr(main, "planning_mode", lambda _description: DummyPlan())
    monkeypatch.setattr(main, "execution_mode", raise_interrupt)

    with pytest.raises(SystemExit):
        main.main()

    captured = capsys.readouterr().out
    assert calls["state_manager_created"] is True
    assert calls["on_interrupt"] is True
    # The resume hint should be printed when on_interrupt runs.
    assert "rev --resume" in captured
