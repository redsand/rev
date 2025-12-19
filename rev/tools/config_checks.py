#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI config validation and migration sanity tools."""

import json
import shlex
from pathlib import Path
from typing import Dict, Any, List, Optional

from rev import config
from rev.tools.utils import _run_shell, _safe_path


def validate_ci_config(paths: Optional[List[str]] = None) -> str:
    """Validate CI configuration files (GitHub Actions / generic YAML)."""
    try:
        resolved = [_safe_path(p) for p in (paths or [])] or list((config.ROOT / ".github" / "workflows").glob("*.yml"))
        results: List[Dict[str, Any]] = []

        # actionlint for GitHub workflows
        workflow_files = [p for p in resolved if p.exists() and p.is_file()]
        if workflow_files:
            cmd = "actionlint " + " ".join(shlex.quote(str(p)) for p in workflow_files)
            proc = _run_shell(cmd, timeout=120)
            if proc.returncode == 127:
                results.append({"tool": "actionlint", "error": "actionlint not installed"})
            else:
                results.append({"tool": "actionlint", "output": proc.stdout, "returncode": proc.returncode})

        # yamllint as fallback
        yaml_files = [p for p in resolved if p.suffix in [".yml", ".yaml"]]
        if yaml_files:
            cmd = "yamllint " + " ".join(shlex.quote(str(p)) for p in yaml_files)
            proc = _run_shell(cmd, timeout=120)
            if proc.returncode != 127:
                results.append({"tool": "yamllint", "output": proc.stdout, "returncode": proc.returncode})

        return json.dumps(
            {"results": results, "checked_files": [p.relative_to(config.ROOT).as_posix() for p in workflow_files]},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"error": f"CI validation failed: {type(e).__name__}: {e}"})


def verify_migrations(path: str = "migrations") -> str:
    """Lightweight migration sanity check (structure/dry-run)."""
    try:
        mig_path = _safe_path(path)
        if not mig_path.exists():
            return json.dumps({"error": f"Path not found: {path}"})

        migration_files = list(mig_path.rglob("*.py")) + list(mig_path.rglob("*.sql"))
        summary = {
            "path": mig_path.relative_to(config.ROOT).as_posix(),
            "files_found": len(migration_files),
            "files": [f.relative_to(config.ROOT).as_posix() for f in migration_files][:50]
        }

        # Attempt Alembic dry-run if config exists
        alembic_ini = config.ROOT / "alembic.ini"
        if alembic_ini.exists():
            proc = _run_shell("alembic upgrade head --sql", timeout=300)
            summary["alembic_dry_run_rc"] = proc.returncode
            summary["alembic_output_sample"] = (proc.stdout + proc.stderr)[:4000]

        return json.dumps({"summary": summary}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Migration verification failed: {type(e).__name__}: {e}"})
