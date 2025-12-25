#!/usr/bin/env python3
"""Setup script for rev - CI/CD Agent powered by Ollama."""

import subprocess
from pathlib import Path
from setuptools import find_packages, setup
from setuptools.command.build_py import build_py
from setuptools.command.install import install


def get_git_commit():
    """Get the current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def update_version_file_with_git_hash():
    """Update _version.py with the current git commit hash."""
    version_file = Path(__file__).parent / "rev" / "_version.py"
    if not version_file.exists():
        return

    git_commit = get_git_commit()

    # Read current content
    content = version_file.read_text(encoding="utf-8")

    # Update the REV_GIT_COMMIT line
    lines = content.split('\n')
    updated_lines = []
    for line in lines:
        if line.startswith('REV_GIT_COMMIT'):
            updated_lines.append(f'REV_GIT_COMMIT = "{git_commit}"')
        else:
            updated_lines.append(line)

    # Write back
    version_file.write_text('\n'.join(updated_lines), encoding="utf-8")
    print(f"Updated _version.py with git commit: {git_commit}")


class BuildPyCommand(build_py):
    """Custom build command to capture git hash."""

    def run(self):
        update_version_file_with_git_hash()
        super().run()


class InstallCommand(install):
    """Custom install command to capture git hash."""

    def run(self):
        update_version_file_with_git_hash()
        super().run()


# Avoid importing the package during setup to prevent dependency import errors
version_ns = {}
version_file = Path(__file__).parent / "rev" / "_version.py"
if version_file.exists():
    exec(version_file.read_text(encoding="utf-8"), version_ns)
REV_VERSION = version_ns.get("REV_VERSION", "0.0.0")

# Read the README file
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

# Read requirements
requirements_file = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_file.exists():
    requirements = [
        line.strip()
        for line in requirements_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="rev-agentic",
    version=REV_VERSION,
    description="Rev - Autonomous AI Development System with Multi-Agent Orchestration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Rev Team",
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        # Development extras
        'dev': [
            'pytest>=7.0.0',
            'pytest-asyncio>=0.21.0',
            'pytest-cov>=4.0.0',
            'black>=23.0.0',
            'mypy>=1.0.0',
            'pylint>=2.16.0',
        ],
    },
    packages=find_packages(
        exclude=["tests", "tests.*", "examples", "examples.*", "build", "build.*"]
    ),
    entry_points={
        "console_scripts": [
            "rev=rev.main:main",
        ],
    },
    cmdclass={
        'build_py': BuildPyCommand,
        'install': InstallCommand,
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Software Development :: Testing",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="ai agent ollama autonomous development orchestration ci-cd testing automation",
    project_urls={
        "Source": "https://github.com/redsand/rev",
        "Bug Reports": "https://github.com/redsand/rev/issues",
        "Documentation": "https://github.com/redsand/rev/blob/main/README.md",
    },
)
