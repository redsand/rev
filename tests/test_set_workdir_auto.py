from pathlib import Path

from rev.execution.orchestrator import Orchestrator, OrchestratorConfig
from rev.models.task import Task
from rev.workspace import Workspace, set_workspace, reset_workspace, get_workspace
import rev.execution.orchestrator as orchestrator_mod


def _init_workspace(base: Path):
    reset_workspace()
    set_workspace(Workspace(root=base))
    return get_workspace()


def test_auto_set_workdir_from_description(monkeypatch):
    base = Path("tmp_test/workdir_auto").resolve()
    frontend = base / "frontend"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")

    workspace = _init_workspace(base)
    orchestrator = Orchestrator(project_root=base, config=OrchestratorConfig())
    calls = []

    def fake_execute_tool(name, args, agent_name=None):
        calls.append((name, args))
        if name == "set_workdir":
            workspace.set_working_dir(args["path"])
            return "ok"
        return "{}"

    monkeypatch.setattr(orchestrator_mod, "execute_tool", fake_execute_tool)

    try:
        task = Task(
            "Install frontend dependencies by running npm install in the frontend directory",
            action_type="test",
        )
        orchestrator._maybe_set_workdir_for_task(task)

        assert calls
        assert calls[0][0] == "set_workdir"
        assert Path(calls[0][1]["path"]).resolve() == frontend
    finally:
        reset_workspace()


def test_auto_set_workdir_skips_explicit_path(monkeypatch):
    base = Path("tmp_test/workdir_auto_skip").resolve()
    frontend = base / "frontend"
    src = frontend / "src"
    src.mkdir(parents=True, exist_ok=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")

    _init_workspace(base)
    orchestrator = Orchestrator(project_root=base, config=OrchestratorConfig())
    calls = []

    def fake_execute_tool(name, args, agent_name=None):
        calls.append((name, args))
        return "ok"

    monkeypatch.setattr(orchestrator_mod, "execute_tool", fake_execute_tool)

    try:
        task = Task(
            "Run npm test frontend/src/app.test.ts",
            action_type="test",
        )
        orchestrator._maybe_set_workdir_for_task(task)

        assert not calls
    finally:
        reset_workspace()
