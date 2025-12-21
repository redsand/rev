#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Property testing, contract checking, and behavioral comparison tools."""

import json
import re
import tempfile
import importlib
import inspect
import textwrap
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from rev import config
from rev.tools.utils import _run_shell, _safe_path, quote_cmd_arg


def _resolve_paths(paths: Optional[List[str]]) -> Tuple[List[Path], List[str]]:
    resolved: List[Path] = []
    missing: List[str] = []
    for p in paths or ["."]:
        try:
            rp = _safe_path(p)
            if rp.exists():
                resolved.append(rp)
            else:
                missing.append(p)
        except Exception:
            missing.append(p)
    return resolved, missing


def run_property_tests(test_paths: Optional[List[str]] = None, max_examples: int = 200) -> str:
    """Run pytest suites that use Hypothesis."""
    try:
        resolved_paths, missing = _resolve_paths(test_paths)
        if not resolved_paths:
            return json.dumps({"error": "No valid test paths", "missing_paths": missing})

        cmd = f"pytest -q --maxfail=50 --disable-warnings --hypothesis-max-examples={max_examples} " + " ".join(
            quote_cmd_arg(str(p)) for p in resolved_paths
        )
        proc = _run_shell(cmd, timeout=900)

        failures = _parse_hypothesis_failures(proc.stdout)
        summary = _parse_pytest_summary(proc.stdout)
        summary.update({
            "returncode": proc.returncode,
            "missing_paths": missing,
            "max_examples": max_examples
        })

        if proc.returncode == 127:
            return json.dumps({
                "error": "pytest not installed",
                "install": "pip install pytest hypothesis",
                "summary": summary
            })

        return json.dumps({"failures": failures, "summary": summary}, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Property tests failed: {type(e).__name__}: {e}"})


def generate_property_tests(targets: List[str], max_examples: int = 200) -> str:
    """Generate Hypothesis property tests for target functions and run them."""
    try:
        if not targets:
            return json.dumps({"error": "No targets provided"})

        generated: List[str] = []
        test_dir = config.ROOT / "tests" / "property"
        test_dir.mkdir(parents=True, exist_ok=True)

        for target in targets:
            file_path, func_name = _split_target(target)
            if not file_path or not func_name:
                continue

            strategy_map = _infer_strategies(file_path, func_name)
            test_code = _build_property_test_code(file_path, func_name, strategy_map, max_examples)

            safe_name = func_name.lower().replace(".", "_").replace("::", "_").replace(":", "_")
            test_file = test_dir / f"test_property_{safe_name}.py"
            test_file.write_text(test_code, encoding="utf-8")
            generated.append(test_file.relative_to(config.ROOT).as_posix())

        run_result = json.loads(run_property_tests([str(test_dir)], max_examples))

        return json.dumps({
            "generated_tests": generated,
            "failures": run_result.get("failures", []),
            "summary": run_result.get("summary", {})
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Generating property tests failed: {type(e).__name__}: {e}"})


def check_contracts(paths: Optional[List[str]] = None, timeout_seconds: int = 60) -> str:
    """Run contract-based analysis using CrossHair."""
    try:
        resolved_paths, missing = _resolve_paths(paths)
        if not resolved_paths:
            return json.dumps({"error": "No valid paths to check", "missing_paths": missing})

        cmd = " ".join(["crosshair", "check", f"--per_path_timeout={timeout_seconds}"] + [
            quote_cmd_arg(str(p)) for p in resolved_paths
        ])
        proc = _run_shell(cmd, timeout=timeout_seconds + 30)

        if proc.returncode == 127:
            return json.dumps({
                "error": "crosshair not installed",
                "install": "pip install crosshair-tool"
            })

        violations = _parse_crosshair(proc.stdout)

        return json.dumps({
            "violations": violations,
            "summary": {
                "returncode": proc.returncode,
                "missing_paths": missing,
                "paths": [p.relative_to(config.ROOT).as_posix() for p in resolved_paths]
            }
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Contract checking failed: {type(e).__name__}: {e}"})


def detect_flaky_tests(pattern: Optional[str] = None, runs: int = 5) -> str:
    """Run pytest multiple times and find flaky tests."""
    try:
        pattern_part = pattern or ""
        collect_cmd = f"pytest -q --collect-only {pattern_part}".strip()
        collected = _run_shell(collect_cmd, timeout=120)
        if collected.returncode == 127:
            return json.dumps({"error": "pytest not installed", "install": "pip install pytest"})

        test_ids = _parse_collected_tests(collected.stdout)
        outcomes: Dict[str, Dict[str, int]] = {tid: {"pass": 0, "fail": 0} for tid in test_ids}
        failures_samples: Dict[str, str] = {}

        for i in range(runs):
            run_cmd = f"pytest -q {pattern_part}".strip()
            proc = _run_shell(run_cmd, timeout=900)
            failed = _parse_failed_tests(proc.stdout)
            for tid in test_ids:
                if tid in failed:
                    outcomes[tid]["fail"] += 1
                    if tid not in failures_samples:
                        failures_samples[tid] = failed[tid]
                else:
                    outcomes[tid]["pass"] += 1

        flaky = []
        for tid, counts in outcomes.items():
            if counts["fail"] and counts["pass"]:
                flaky.append({
                    "test": tid,
                    "pass_count": counts["pass"],
                    "fail_count": counts["fail"],
                    "example_fail_trace": failures_samples.get(tid)
                })

        return json.dumps({
            "flaky": flaky,
            "summary": {
                "runs": runs,
                "pattern": pattern,
                "total_tests": len(test_ids)
            }
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Flaky detection failed: {type(e).__name__}: {e}"})


def compare_behavior_with_baseline(baseline_ref: str = "origin/main", test_selector: Optional[str] = None) -> str:
    """Run tests on baseline ref vs current and diff results."""
    try:
        temp_dir = Path(tempfile.mkdtemp(prefix="rev_baseline_"))
        worktree_cmd = f"git worktree add --detach {quote_cmd_arg(str(temp_dir))} {quote_cmd_arg(baseline_ref)}"
        add_proc = _run_shell(worktree_cmd, timeout=120)
        if add_proc.returncode != 0:
            return json.dumps({"error": "Failed to create baseline worktree", "details": add_proc.stderr})

        selector = test_selector or ""
        test_cmd = f"pytest -q {selector}".strip()

        baseline_proc = _run_shell(test_cmd, timeout=900)
        baseline_summary = _parse_pytest_summary(baseline_proc.stdout)
        baseline_summary["returncode"] = baseline_proc.returncode

        current_proc = _run_shell(test_cmd, timeout=900)
        current_summary = _parse_pytest_summary(current_proc.stdout)
        current_summary["returncode"] = current_proc.returncode

        deltas = _diff_summaries(baseline_summary, current_summary)

        _run_shell(f"git worktree remove {quote_cmd_arg(str(temp_dir))} --force", timeout=60)

        return json.dumps({
            "deltas": deltas,
            "baseline": baseline_summary,
            "current": current_summary
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Behavior comparison failed: {type(e).__name__}: {e}"})


# Helpers


def _parse_pytest_summary(stdout: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for line in stdout.splitlines():
        if "===" in line and "passed" in line:
            summary["summary_line"] = line.strip()
            parts = line.replace("=", "").split()
            for part in parts:
                if "passed" in part:
                    try:
                        summary["passed"] = int(parts[parts.index(part) - 1])
                    except Exception:
                        pass
                if "failed" in part:
                    try:
                        summary["failed"] = int(parts[parts.index(part) - 1])
                    except Exception:
                        pass
                if "xfailed" in part:
                    try:
                        summary["xfailed"] = int(parts[parts.index(part) - 1])
                    except Exception:
                        pass
        if line.startswith("FAILED "):
            summary.setdefault("failed_tests", []).append(line.split()[1])
    return summary


def _parse_hypothesis_failures(stdout: str) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    current_test = None
    collecting = False
    example_lines: List[str] = []
    traceback_lines: List[str] = []

    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            if current_test and example_lines:
                failures.append({
                    "test": current_test,
                    "minimal_example": "\n".join(example_lines).strip(),
                    "traceback": "\n".join(traceback_lines).strip()
                })
            current_test = line.split()[1]
            example_lines = []
            traceback_lines = []
            collecting = False
        elif "Falsifying example:" in line:
            collecting = True
            example_lines.append(line.strip())
        elif collecting:
            if line.strip() == "":
                collecting = False
            else:
                example_lines.append(line.strip())
        elif current_test:
            traceback_lines.append(line)

    if current_test and example_lines:
        failures.append({
            "test": current_test,
            "minimal_example": "\n".join(example_lines).strip(),
            "traceback": "\n".join(traceback_lines).strip()
        })
    return failures


def _split_target(target: str) -> Tuple[Optional[str], Optional[str]]:
    if "::" in target:
        file_part, func = target.split("::", 1)
    elif ":" in target:
        file_part, func = target.split(":", 1)
    else:
        return None, None
    return file_part, func


def _infer_strategies(module_path: str, func_name: str) -> Dict[str, str]:
    """Best-effort strategy mapping based on type hints."""
    strategies: Dict[str, str] = {}
    try:
        module_rel = module_path.replace("/", ".").replace("\\", ".").rstrip(".py")
        module_rel = module_rel[:-3] if module_rel.endswith(".py") else module_rel
        mod = importlib.import_module(module_rel)
        func = getattr(mod, func_name, None)
        if not func:
            return strategies
        sig = inspect.signature(func)
        for name, param in sig.parameters.items():
            annotation = str(param.annotation)
            if "int" in annotation:
                strategies[name] = "st.integers()"
            elif "float" in annotation:
                strategies[name] = "st.floats(allow_nan=False, allow_infinity=False)"
            elif "bool" in annotation:
                strategies[name] = "st.booleans()"
            elif "dict" in annotation:
                strategies[name] = "st.dictionaries(st.text(), st.text())"
            elif "list" in annotation:
                strategies[name] = "st.lists(st.text())"
            else:
                strategies[name] = "st.text()"
    except Exception:
        pass
    return strategies


def _build_property_test_code(module_path: str, func_name: str, strategies: Dict[str, str], max_examples: int) -> str:
    imports = "from hypothesis import given, settings\nimport hypothesis.strategies as st\n"
    module_import = module_path.replace("/", ".").replace("\\", ".").rstrip(".py")
    module_import = module_import[:-3] if module_import.endswith(".py") else module_import
    func_import = f"from {module_import} import {func_name}\n\n"

    if not strategies:
        strategies = {"value": "st.text()"}

    args = ", ".join(f"{name}={value}" for name, value in strategies.items())
    params = ", ".join(strat.split("=")[0] for strat in strategies.keys()) if False else ", ".join(strategies.keys())

    test_body = textwrap.dedent(f"""
    @settings(max_examples={max_examples})
    @given({args})
    def test_property_{func_name.lower()}({params}):
        # Property: function should not raise and should produce consistent type
        result = {func_name}({params})
        assert result is None or isinstance(result, (int, float, str, bool, dict, list, tuple))
    """)

    return imports + func_import + test_body


def _parse_crosshair(stdout: str) -> List[Dict[str, Any]]:
    violations = []
    for block in stdout.split("\n\n"):
        if "failed for" in block:
            lines = block.strip().splitlines()
            header = lines[0]
            parts = header.split(" failed for ")
            func = parts[0].strip()
            contract = parts[1] if len(parts) > 1 else ""
            violations.append({
                "function": func,
                "contract": contract,
                "counterexample": "\n".join(lines[1:]).strip()
            })
    return violations


def _parse_collected_tests(stdout: str) -> List[str]:
    tests = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("="):
            continue
        tests.append(line)
    return tests


def _parse_failed_tests(stdout: str) -> Dict[str, str]:
    failed: Dict[str, str] = {}
    current = None
    trace: List[str] = []
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            if current:
                failed[current] = "\n".join(trace)
            current = line.split()[1]
            trace = []
        elif current:
            trace.append(line)
    if current:
        failed[current] = "\n".join(trace)
    return failed


def _diff_summaries(baseline: Dict[str, Any], current: Dict[str, Any]) -> List[Dict[str, Any]]:
    deltas = []
    keys = set(baseline.keys()) | set(current.keys())
    for key in keys:
        if baseline.get(key) != current.get(key):
            deltas.append({
                "metric": key,
                "baseline": baseline.get(key),
                "current": current.get(key),
                "diff_summary": f"{key}: {baseline.get(key)} -> {current.get(key)}"
            })
    return deltas


def bisect_test_failure(test_command: str, good_ref: Optional[str] = None, bad_ref: str = "HEAD") -> str:
    """Automate git bisect to find the commit introducing a failing test."""
    try:
        if not good_ref:
            return json.dumps({"error": "good_ref is required for bisect"})

        script = Path(tempfile.mkdtemp(prefix="rev_bisect_")) / "run_test.sh"
        script.write_text(f"#!/bin/sh\n{test_command}\n", encoding="utf-8")

        _run_shell(f"git bisect start {quote_cmd_arg(bad_ref)} {quote_cmd_arg(good_ref)}", timeout=60)
        result = _run_shell(f"git bisect run sh {quote_cmd_arg(str(script))}", timeout=1800)
        log = result.stdout + "\n" + (result.stderr or "")
        culprit = None
        for line in log.splitlines():
            if line.startswith("bisect found first bad commit"):
                parts = line.split()
                if len(parts) >= 6:
                    culprit = parts[-1]
        _run_shell("git bisect reset", timeout=60)

        return json.dumps({
            "culprit_commit": culprit,
            "returncode": result.returncode,
            "output": log[-4000:]
        }, indent=2)
    except Exception as e:
        _run_shell("git bisect reset", timeout=60)
        return json.dumps({"error": f"Bisect failed: {type(e).__name__}: {e}"})


def generate_repro_case(context: str, target_path: str = "tests/regressions/test_repro_case.py") -> str:
    """Generate a minimal failing regression test from provided context/logs."""
    try:
        target = _safe_path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sanitized = "\n".join(context.splitlines()[:50])
        context_comment = sanitized.replace('"', '\\"')
        test_code = textwrap.dedent(
            f"""\
            import pytest


            def test_generated_repro():
                # Context (truncated):
                # {context_comment}
                pytest.fail("Generated repro placeholder - replace with concrete assertions")
            """
        )
        target.write_text(test_code, encoding="utf-8")
        proc = _run_shell(f"pytest -q {quote_cmd_arg(str(target))}", timeout=300)
        return json.dumps({
            "test_path": target.relative_to(config.ROOT).as_posix(),
            "run_output": (proc.stdout + proc.stderr)[:4000],
            "returncode": proc.returncode
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Generate repro failed: {type(e).__name__}: {e}"})
