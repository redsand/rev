import json
from pathlib import Path
from typing import Dict, Any, Optional
from rev import config

_TEST_SCRIPT_PRIORITY = (
    "test:ci",
    "test:unit",
    "test:integration",
    "test:e2e",
    "test:all",
    "test:api",
    "test:backend",
    "test:frontend",
)


def _load_package_json(root: Path) -> Optional[Dict[str, Any]]:
    try:
        pkg_path = root / "package.json"
        if not pkg_path.exists():
            return None
        return json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _detect_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _is_placeholder_test_script(script: str) -> bool:
    if not script:
        return True
    lowered = script.lower()
    if "no test specified" in lowered:
        return True
    if "echo" in lowered and "test specified" in lowered and "exit 1" in lowered:
        return True
    return False


def _select_test_script(scripts: Dict[str, Any]) -> Optional[str]:
    if not scripts:
        return None
    script = scripts.get("test")
    if isinstance(script, str) and not _is_placeholder_test_script(script):
        return "test"
    for key in _TEST_SCRIPT_PRIORITY:
        script = scripts.get(key)
        if isinstance(script, str) and not _is_placeholder_test_script(script):
            return key
    for key in sorted(scripts.keys()):
        if key.startswith(("pretest", "posttest")):
            continue
        if key.startswith(("test:", "test-")):
            script = scripts.get(key)
            if isinstance(script, str) and not _is_placeholder_test_script(script):
                return key
    for key in sorted(scripts.keys()):
        if key.startswith(("pretest", "posttest")):
            continue
        if "test" in key:
            script = scripts.get(key)
            if isinstance(script, str) and not _is_placeholder_test_script(script):
                return key
    return None


def _node_test_runner_command(package_data: Dict[str, Any]) -> Optional[list[str]]:
    deps: Dict[str, Any] = {}
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        data = package_data.get(section)
        if isinstance(data, dict):
            deps.update(data)

    runner_map = (
        ("vitest", ["npx", "--yes", "vitest", "run"]),
        ("jest", ["npx", "--yes", "jest"]),
        ("mocha", ["npx", "--yes", "mocha"]),
        ("ava", ["npx", "--yes", "ava"]),
        ("tap", ["npx", "--yes", "tap"]),
        ("jasmine", ["npx", "--yes", "jasmine"]),
        ("uvu", ["npx", "--yes", "uvu"]),
        ("playwright", ["npx", "--yes", "playwright", "test"]),
        ("cypress", ["npx", "--yes", "cypress", "run"]),
    )

    for runner, cmd in runner_map:
        if runner in deps:
            return cmd

    return None

def find_project_root(path: Path) -> Path:
    """Find the nearest project root containing project markers, staying within workspace."""
    try:
        # Standardize path
        path = path.resolve()
        
        # Determine the search limit (workspace root)
        try:
            root_limit = config.ROOT.resolve()
        except Exception:
            root_limit = Path.cwd().resolve()
            
        # Markers that indicate a project root
        markers = {
            "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "pyproject.toml", "requirements.txt", "setup.py",
            "go.mod", "Cargo.toml", "Gemfile", "composer.json", "composer.lock",
            "pom.xml", "build.gradle", "build.gradle.kts", "gradlew",
            "CMakeLists.txt", "Makefile", "pubspec.yaml", "Package.swift",
            ".git", ".rev"
        }
        
        current = path
        # If path is a file, start from its parent
        if current.is_file():
            current = current.parent
            
        while True:
            # Check for markers
            if any((current / marker).exists() for marker in markers):
                return current
                
            # Stop if we reached the workspace root or the system root
            if current == root_limit:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
            
        return root_limit
    except Exception:
        # Fallback to module-level ROOT
        try:
            return config.ROOT
        except:
            return Path(".").resolve()

def detect_project_type(path: Path) -> str:
    """Detect the project type (python, vue, node, go, rust, etc) relative to a path."""
    try:
        root = find_project_root(path)
        
        # 1. Node.js Ecosystem
        if (root / "package.json").exists():
            content = (root / "package.json").read_text(errors="ignore")
            if '"vue"' in content: return "vue"
            if '"react"' in content: return "react"
            if '"next"' in content: return "nextjs"
            return "node"
        
        # 2. Python Ecosystem
        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
            return "python"
            
        # 3. Go Ecosystem
        if (root / "go.mod").exists():
            return "go"
            
        # 4. Rust Ecosystem
        if (root / "Cargo.toml").exists():
            return "rust"
            
        # 5. Ruby Ecosystem
        if (root / "Gemfile").exists() or (root / "Rakefile").exists():
            return "ruby"
            
        # 6. PHP Ecosystem
        if (root / "composer.json").exists():
            return "php"
            
        # 7. Java/Kotlin Ecosystem
        if (root / "pom.xml").exists():
            return "java_maven"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            # Check if it's Kotlin
            if any(root.rglob("*.kt")):
                return "kotlin"
            return "java_gradle"
            
        # 8. C# / .NET Ecosystem
        if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
            return "csharp"
            
        # 9. C/C++ Ecosystem
        if (root / "CMakeLists.txt").exists():
            return "cpp_cmake"
        if (root / "Makefile").exists():
            return "cpp_make"
            
        # 10. Mobile / Flutter
        if (root / "pubspec.yaml").exists():
            return "flutter"

        # Fallback by file extension in root
        if root.exists() and root.is_dir():
            for f in root.iterdir():
                if f.suffix == ".py": return "python"
                if f.suffix in (".js", ".ts"): return "node"
                if f.suffix == ".go": return "go"
                if f.suffix == ".rs": return "rust"
                if f.suffix == ".rb": return "ruby"
                if f.suffix == ".php": return "php"
                if f.suffix == ".java": return "java_maven"
                if f.suffix == ".kt": return "kotlin"
                if f.suffix == ".cs": return "csharp"
    except Exception:
        pass
    return "unknown"


def detect_test_command(path: Path) -> Optional[list[str]]:
    """Detect a project-appropriate test command based on repo markers."""
    try:
        root = find_project_root(path)
        if not root.exists():
            return None

        if (root / "package.json").exists():
            package_data = _load_package_json(root)
            package_manager = _detect_package_manager(root)
            if package_data:
                scripts = package_data.get("scripts")
                if isinstance(scripts, dict):
                    script_name = _select_test_script(scripts)
                    if script_name:
                        if package_manager == "npm":
                            return ["npm", "test"] if script_name == "test" else ["npm", "run", script_name]
                        if package_manager == "pnpm":
                            return ["pnpm", "test"] if script_name == "test" else ["pnpm", "run", script_name]
                        return ["yarn", "test"] if script_name == "test" else ["yarn", "run", script_name]
                runner_cmd = _node_test_runner_command(package_data)
                if runner_cmd:
                    return runner_cmd
                return None
            if package_manager == "pnpm":
                return ["pnpm", "test"]
            if package_manager == "yarn":
                return ["yarn", "test"]
            return ["npm", "test"]

        if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
            return ["pytest", "-q"]

        if (root / "go.mod").exists():
            return ["go", "test", "./..."]

        if (root / "Cargo.toml").exists():
            return ["cargo", "test"]

        if (root / "pom.xml").exists():
            return ["mvn", "test"]

        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            if (root / "gradlew").exists():
                return ["./gradlew", "test"]
            return ["gradle", "test"]

        if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
            return ["dotnet", "test"]

        if (root / "Gemfile").exists():
            if (root / "spec").exists():
                return ["bundle", "exec", "rspec"]
            return ["bundle", "exec", "rake", "test"]

        if (root / "composer.json").exists():
            return ["vendor/bin/phpunit"]

        if (root / "pubspec.yaml").exists():
            try:
                content = (root / "pubspec.yaml").read_text(errors="ignore")
                if "flutter:" in content:
                    return ["flutter", "test"]
            except Exception:
                pass
            return ["dart", "test"]

        if (root / "Package.swift").exists():
            return ["swift", "test"]

        if (root / "Makefile").exists():
            return ["make", "test"]

        if (root / "CMakeLists.txt").exists():
            return ["ctest"]
    except Exception:
        return None

    return None
