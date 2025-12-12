#!/usr/bin/env python3
"""Setup script for rev - CI/CD Agent powered by Ollama."""

from pathlib import Path
from setuptools import find_packages, setup

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
    packages=find_packages(
        exclude=["tests", "tests.*", "examples", "examples.*", "build", "build.*"]
    ),
    entry_points={
        "console_scripts": [
            "rev=rev.main:main",
        ],
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
