#!/usr/bin/env python3
"""Setup script for rev - CI/CD Agent powered by Ollama."""

from setuptools import setup, find_packages
from pathlib import Path

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
    name="rev",
    version="0.1.0",
    description="CI/CD Agent powered by Ollama - Minimal autonomous agent with single-gate approval",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Rev Team",
    python_requires=">=3.8",
    install_requires=requirements,
    packages=find_packages(exclude=["tests", "tests.*", "examples", "examples.*"]),
    entry_points={
        "console_scripts": [
            "rev=rev.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
