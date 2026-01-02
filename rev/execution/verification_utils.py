import json
from pathlib import Path
from typing import Optional


def _detect_build_command_for_root(root: Path) -> Optional[str]:
    """Return a project-appropriate build/typecheck command if one exists."""
    try:
        root = Path(root)
    except Exception:
        root = Path.cwd()

    # JS/TS project with build script
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
        if isinstance(scripts, dict):
            for key in ("build", "typecheck", "compile"):
                if key in scripts:
                    return f"npm run {key}"
        deps = set()
        for field in ("dependencies", "devDependencies", "peerDependencies"):
            values = data.get(field, {})
            if isinstance(values, dict):
                deps.update({str(k).strip().lower() for k in values.keys()})
        if "typescript" in deps:
            return "npx tsc --noEmit"

    # Go
    if (root / "go.mod").exists():
        return "go build ./..."

    # Rust
    if (root / "Cargo.toml").exists():
        return "cargo build"

    # .NET
    if any(root.glob("*.sln")) or any(root.glob("*.csproj")):
        return "dotnet build"

    # Java
    if (root / "pom.xml").exists():
        return "mvn -q -DskipTests package"
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        if (root / "gradlew").exists():
            return "./gradlew build -x test"
        return "gradle build -x test"

    # Python: compileall as a lightweight syntax check
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return "python -m compileall ."

    return None
