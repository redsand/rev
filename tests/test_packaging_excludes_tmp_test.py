import ast
from pathlib import Path


def _extract_find_packages_exclude() -> list[str]:
    setup_path = Path(__file__).resolve().parents[1] / "setup.py"
    tree = ast.parse(setup_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "find_packages":
            for keyword in node.keywords:
                if keyword.arg != "exclude":
                    continue
                return ast.literal_eval(keyword.value)
    return []


def _extract_pyproject_exclude() -> list[str]:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == "[tool.setuptools.packages.find]"
            continue
        if in_section and stripped.startswith("exclude"):
            _, value = stripped.split("=", 1)
            return ast.literal_eval(value.strip())
    return []


def test_setup_excludes_tmp_test():
    excludes = _extract_find_packages_exclude()
    assert "tmp_test" in excludes
    assert "tmp_test.*" in excludes


def test_pyproject_excludes_tmp_test():
    excludes = _extract_pyproject_exclude()
    assert "tmp_test*" in excludes
