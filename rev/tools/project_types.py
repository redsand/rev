import json
from pathlib import Path
from typing import Dict, Any, Optional
from rev import config

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
            "package.json", "pyproject.toml", "requirements.txt", "setup.py",
            "go.mod", "Cargo.toml", "Gemfile", "composer.json", "pom.xml",
            "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile",
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
