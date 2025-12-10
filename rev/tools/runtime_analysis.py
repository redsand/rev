#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime log and performance analysis tools."""

import json
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from rev.config import ROOT
from rev.tools.utils import _run_shell, _safe_path
from rev.tools.advanced_analysis import analyze_code_context, analyze_dependencies


def _resolve_paths(paths: Optional[List[str]]) -> Tuple[List[Path], List[str]]:
    resolved: List[Path] = []
    missing: List[str] = []
    for p in paths or []:
        try:
            rp = _safe_path(p)
            if rp.exists():
                resolved.append(rp)
            else:
                missing.append(p)
        except Exception:
            missing.append(p)
    return resolved, missing


def analyze_runtime_logs(log_paths: List[str], since: Optional[str] = None) -> str:
    """Parse logs for warnings/errors/tracebacks."""
    try:
        resolved, missing = _resolve_paths(log_paths)
        if not resolved:
            return json.dumps({"error": "No valid log paths", "missing_paths": missing})

        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except Exception:
                pass

        issues: Dict[str, Dict[str, Any]] = {}

        warning_re = re.compile(r"\bWARNING\b|\bWARN\b", re.IGNORECASE)
        error_re = re.compile(r"\bERROR\b|\bERR\b", re.IGNORECASE)
        traceback_re = re.compile(r"Traceback \(most recent call last\):")

        def add_issue(kind: str, message: str, file: str, line_no: int) -> None:
            key = f"{kind}:{message}:{file}:{line_no}"
            if key not in issues:
                issues[key] = {"kind": kind, "message": message.strip(), "file": file, "line": line_no, "count": 0}
            issues[key]["count"] += 1

        for log_file in resolved:
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            for idx, line in enumerate(lines, 1):
                if since_dt and not _line_after(line, since_dt):
                    continue
                if traceback_re.search(line):
                    trace_block = _collect_trace(lines, idx - 1)
                    add_issue("traceback", trace_block, str(log_file.relative_to(ROOT)), idx)
                elif warning_re.search(line):
                    add_issue("warning", line.strip(), str(log_file.relative_to(ROOT)), idx)
                elif error_re.search(line):
                    add_issue("error", line.strip(), str(log_file.relative_to(ROOT)), idx)

        return json.dumps({"issues": list(issues.values()), "summary": {"files": [str(p.relative_to(ROOT)) for p in resolved], "missing_paths": missing}}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Runtime log analysis failed: {type(e).__name__}: {e}"})


def analyze_performance_regression(
    benchmark_cmd: str,
    baseline_file: str = ".rev-metrics/perf-baseline.json",
    tolerance_pct: float = 10.0
) -> str:
    """Run benchmarks and compare against baseline."""
    try:
        baseline_path = _safe_path(baseline_file)
        baseline = {}
        if baseline_path.exists():
            try:
                baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            except Exception:
                baseline = {}

        proc = _run_shell(benchmark_cmd, timeout=1200)
        if proc.returncode == 127:
            return json.dumps({"error": "benchmark command failed to run", "details": proc.stderr})

        current = _parse_benchmark_output(proc.stdout)

        regressions = []
        for name, cur_val in current.items():
            base_val = baseline.get(name)
            if base_val is None:
                continue
            if base_val == 0:
                continue
            delta_pct = ((cur_val - base_val) / base_val) * 100
            if delta_pct > tolerance_pct:
                regressions.append({"name": name, "baseline": base_val, "current": cur_val, "delta_pct": round(delta_pct, 2)})

        summary = {
            "returncode": proc.returncode,
            "benchmarks_seen": len(current),
            "baseline_file": str(baseline_path.relative_to(ROOT)),
            "tolerance_pct": tolerance_pct
        }

        return json.dumps({"regressions": regressions, "current": current, "baseline": baseline, "summary": summary}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Performance regression analysis failed: {type(e).__name__}: {e}"})


def analyze_error_traces(log_paths: List[str], max_traces: int = 200) -> str:
    """Cluster error/stack traces and map to suspect modules."""
    try:
        resolved, missing = _resolve_paths(log_paths)
        if not resolved:
            return json.dumps({"error": "No valid log paths", "missing_paths": missing})

        traces = []
        traceback_re = re.compile(r"Traceback \(most recent call last\):")

        for log_file in resolved:
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                continue

            idx = 0
            while idx < len(lines) and len(traces) < max_traces:
                line = lines[idx]
                if traceback_re.search(line):
                    block = _collect_trace(lines, idx)
                    traces.append(block)
                    idx += len(block.splitlines())
                else:
                    idx += 1

        clusters: Dict[str, Dict[str, Any]] = {}
        for trace in traces:
            signature = _trace_signature(trace)
            if signature not in clusters:
                clusters[signature] = {
                    "signature": signature,
                    "count": 0,
                    "sample_trace": trace,
                    "suspected_files": _suspect_files(trace)
                }
            clusters[signature]["count"] += 1

        return json.dumps({"clusters": list(clusters.values()), "summary": {"total_traces": len(traces), "missing_paths": missing}}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Error trace analysis failed: {type(e).__name__}: {e}"})


# Helpers


def _line_after(line: str, since_dt: datetime) -> bool:
    try:
        ts_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
        if ts_match:
            dt = datetime.fromisoformat(ts_match.group(0))
            return dt >= since_dt
    except Exception:
        pass
    return True


def _collect_trace(lines: List[str], start_idx: int) -> str:
    block = []
    for line in lines[start_idx:]:
        block.append(line.rstrip("\n"))
        if line.strip() == "" and len(block) > 1:
            break
    return "\n".join(block)


def _parse_benchmark_output(stdout: str) -> Dict[str, float]:
    """Parse pytest-benchmark or codspeed-like output (best-effort)."""
    results: Dict[str, float] = {}
    bench_re = re.compile(r"([\w\./:-]+)\s+([\d\.]+)\s*(ns|us|ms|s)")
    unit_scale = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
    for line in stdout.splitlines():
        m = bench_re.search(line)
        if m:
            name, value, unit = m.groups()
            results[name] = float(value) * unit_scale.get(unit, 1.0)
    return results


def _trace_signature(trace: str) -> str:
    lines = trace.splitlines()
    exc_line = ""
    for line in reversed(lines):
        if line.strip():
            exc_line = line.strip()
            break
    top_frame = ""
    for line in lines:
        if line.strip().startswith('File '):
            top_frame = line.strip()
            break
    return f"{exc_line} | {top_frame}"


def _suspect_files(trace: str) -> List[str]:
    files = []
    for line in trace.splitlines():
        if line.strip().startswith("File "):
            parts = line.split(",")
            if parts:
                path_part = parts[0].replace("File", "").strip().strip('"').strip("'")
                files.append(path_part)
    return files[:5]
