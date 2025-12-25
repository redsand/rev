import json
from pathlib import Path


def test_vscode_extension_has_build_script() -> None:
    package_path = Path("ide-extensions") / "vscode" / "package.json"
    data = json.loads(package_path.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    assert "build" in scripts
    assert "vsce" in scripts["build"]


def test_vscode_extension_has_vsce_dependency() -> None:
    package_path = Path("ide-extensions") / "vscode" / "package.json"
    data = json.loads(package_path.read_text(encoding="utf-8"))
    dev_deps = data.get("devDependencies", {})
    assert "@vscode/vsce" in dev_deps


def test_vscode_extension_has_metadata_files() -> None:
    root = Path("ide-extensions") / "vscode"
    package_path = root / "package.json"
    data = json.loads(package_path.read_text(encoding="utf-8"))
    assert data.get("repository", {}).get("url")
    assert data.get("license") == "MIT"
    assert (root / "LICENSE").exists()
    assert (root / ".vscodeignore").exists()


def test_vscodeignore_keeps_runtime_deps() -> None:
    ignore_path = Path("ide-extensions") / "vscode" / ".vscodeignore"
    contents = ignore_path.read_text(encoding="utf-8")
    assert "node_modules/**" not in contents
