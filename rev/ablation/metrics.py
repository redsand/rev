#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Metrics and reporting for ablation experiments.

This module provides functions for analyzing benchmark results
and comparing different feature configurations.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from rev.ablation.feature_flags import Features
from rev.ablation.benchmark import BenchmarkResult


@dataclass
class AblationMetrics:
    """Aggregate metrics across benchmark runs."""
    feature_config: Set[Features]
    win_rate: float  # % tasks succeeded
    avg_time_seconds: float
    avg_iterations: int
    avg_loops_avoided: int
    avg_tokens: int
    num_tasks: int

    def __str__(self) -> str:
        """String representation of metrics."""
        features_str = ", ".join(f.value for f in sorted(self.feature_config, key=lambda x: x.value))
        return (
            f"Features: {features_str}\n"
            f"  Win rate: {self.win_rate:.1%}\n"
            f"  Avg time: {self.avg_time_seconds:.1f}s\n"
            f"  Avg iterations: {self.avg_iterations:.1f}\n"
            f"  Avg loops avoided: {self.avg_loops_avoided:.1f}\n"
            f"  Avg tokens: {self.avg_tokens:.0f}\n"
            f"  Tasks: {self.num_tasks}"
        )


def calculate_metrics(results: List[BenchmarkResult]) -> AblationMetrics:
    """Calculate aggregate metrics from results.

    Args:
        results: List of benchmark results (should all have same feature config)

    Returns:
        AblationMetrics with aggregate statistics
    """
    if not results:
        # Return empty metrics for no results
        return AblationMetrics(
            feature_config=set(),
            win_rate=0.0,
            avg_time_seconds=0.0,
            avg_iterations=0.0,
            avg_loops_avoided=0.0,
            avg_tokens=0.0,
            num_tasks=0
        )

    # Use feature config from first result (assume all same)
    feature_config = results[0].feature_config

    # Calculate aggregates
    num_tasks = len(results)
    num_successes = sum(1 for r in results if r.success)
    total_time = sum(r.time_seconds for r in results)
    total_iterations = sum(r.iterations for r in results)
    total_loops_avoided = sum(r.loops_avoided for r in results)
    total_tokens = sum(r.tokens_used for r in results)

    return AblationMetrics(
        feature_config=feature_config,
        win_rate=num_successes / num_tasks if num_tasks > 0 else 0.0,
        avg_time_seconds=total_time / num_tasks if num_tasks > 0 else 0.0,
        avg_iterations=total_iterations / num_tasks if num_tasks > 0 else 0.0,
        avg_loops_avoided=total_loops_avoided / num_tasks if num_tasks > 0 else 0.0,
        avg_tokens=total_tokens / num_tasks if num_tasks > 0 else 0.0,
        num_tasks=num_tasks
    )


def compare_configs(baseline: AblationMetrics, experimental: AblationMetrics) -> str:
    """Generate comparison report between two configurations.

    Args:
        baseline: Metrics for baseline configuration
        experimental: Metrics for experimental configuration

    Returns:
        String report showing differences
    """
    lines = []
    lines.append("=" * 60)
    lines.append("ABLATION COMPARISON REPORT")
    lines.append("=" * 60)
    lines.append("")

    lines.append("BASELINE:")
    lines.append(str(baseline))
    lines.append("")

    lines.append("EXPERIMENTAL:")
    lines.append(str(experimental))
    lines.append("")

    lines.append("DIFFERENCES:")
    lines.append("-" * 60)

    # Win rate comparison
    win_rate_diff = experimental.win_rate - baseline.win_rate
    win_rate_pct = (win_rate_diff / baseline.win_rate * 100) if baseline.win_rate > 0 else 0.0
    lines.append(f"Win rate: {win_rate_diff:+.1%} ({win_rate_pct:+.1f}%)")

    # Time comparison
    time_diff = experimental.avg_time_seconds - baseline.avg_time_seconds
    time_pct = (time_diff / baseline.avg_time_seconds * 100) if baseline.avg_time_seconds > 0 else 0.0
    lines.append(f"Avg time: {time_diff:+.1f}s ({time_pct:+.1f}%)")

    # Iterations comparison
    iter_diff = experimental.avg_iterations - baseline.avg_iterations
    iter_pct = (iter_diff / baseline.avg_iterations * 100) if baseline.avg_iterations > 0 else 0.0
    lines.append(f"Avg iterations: {iter_diff:+.1f} ({iter_pct:+.1f}%)")

    # Loops avoided comparison
    loops_diff = experimental.avg_loops_avoided - baseline.avg_loops_avoided
    loops_pct = (loops_diff / baseline.avg_loops_avoided * 100) if baseline.avg_loops_avoided > 0 else 0.0
    lines.append(f"Avg loops avoided: {loops_diff:+.1f} ({loops_pct:+.1f}%)")

    # Tokens comparison
    tokens_diff = experimental.avg_tokens - baseline.avg_tokens
    tokens_pct = (tokens_diff / baseline.avg_tokens * 100) if baseline.avg_tokens > 0 else 0.0
    lines.append(f"Avg tokens: {tokens_diff:+.0f} ({tokens_pct:+.1f}%)")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def group_results_by_config(results: List[BenchmarkResult]) -> Dict[frozenset, List[BenchmarkResult]]:
    """Group results by feature configuration.

    Args:
        results: List of all benchmark results

    Returns:
        Dictionary mapping feature configs to their results
    """
    grouped = {}
    for result in results:
        # Use frozenset as dict key (sets aren't hashable)
        config_key = frozenset(result.feature_config)
        if config_key not in grouped:
            grouped[config_key] = []
        grouped[config_key].append(result)

    return grouped


def generate_ablation_report(all_results: List[BenchmarkResult], output_path: Path) -> Path:
    """Generate full HTML/markdown report from ablation results.

    Args:
        all_results: All benchmark results
        output_path: Path for output file

    Returns:
        Path to generated report
    """
    # Group results by feature configuration
    grouped = group_results_by_config(all_results)

    # Calculate metrics for each config
    config_metrics = {}
    for config_key, results in grouped.items():
        metrics = calculate_metrics(results)
        config_metrics[config_key] = metrics

    # Generate markdown report
    lines = []
    lines.append("# Ablation Experiment Report")
    lines.append("")
    lines.append(f"**Total Results:** {len(all_results)}")
    lines.append(f"**Configurations Tested:** {len(grouped)}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Configuration | Win Rate | Avg Time | Avg Iterations | Avg Tokens |")
    lines.append("|--------------|----------|----------|----------------|------------|")

    for config_key, metrics in sorted(config_metrics.items(), key=lambda x: x[1].win_rate, reverse=True):
        features_str = ", ".join(sorted(f.value for f in metrics.feature_config))
        if not features_str:
            features_str = "baseline"

        lines.append(
            f"| {features_str[:40]} | {metrics.win_rate:.1%} | "
            f"{metrics.avg_time_seconds:.1f}s | {metrics.avg_iterations:.1f} | "
            f"{metrics.avg_tokens:.0f} |"
        )

    lines.append("")
    lines.append("## Detailed Results")
    lines.append("")

    for config_key, metrics in config_metrics.items():
        features_str = ", ".join(sorted(f.value for f in metrics.feature_config))
        if not features_str:
            features_str = "baseline"

        lines.append(f"### {features_str}")
        lines.append("")
        lines.append(f"- **Win Rate:** {metrics.win_rate:.1%}")
        lines.append(f"- **Average Time:** {metrics.avg_time_seconds:.1f}s")
        lines.append(f"- **Average Iterations:** {metrics.avg_iterations:.1f}")
        lines.append(f"- **Average Loops Avoided:** {metrics.avg_loops_avoided:.1f}")
        lines.append(f"- **Average Tokens:** {metrics.avg_tokens:.0f}")
        lines.append(f"- **Tasks:** {metrics.num_tasks}")
        lines.append("")

        # Show individual task results
        results = grouped[config_key]
        lines.append("**Task Results:**")
        lines.append("")
        for result in results:
            status = "✅" if result.success else "❌"
            lines.append(f"- {status} {result.task_name} ({result.time_seconds:.1f}s)")
        lines.append("")

    # Write report
    with open(output_path, 'w') as f:
        f.write("\n".join(lines))

    return output_path


def find_best_config(all_results: List[BenchmarkResult]) -> Set[Features]:
    """Find the feature configuration with best win rate.

    Args:
        all_results: All benchmark results

    Returns:
        Set of features for best configuration
    """
    grouped = group_results_by_config(all_results)

    best_config = None
    best_win_rate = -1.0

    for config_key, results in grouped.items():
        metrics = calculate_metrics(results)
        if metrics.win_rate > best_win_rate:
            best_win_rate = metrics.win_rate
            best_config = metrics.feature_config

    return best_config or set()


def feature_impact_analysis(all_results: List[BenchmarkResult]) -> Dict[Features, float]:
    """Analyze impact of each individual feature.

    This compares win rates with/without each feature to estimate
    its marginal contribution.

    Args:
        all_results: All benchmark results

    Returns:
        Dictionary mapping features to their estimated impact (win rate delta)
    """
    grouped = group_results_by_config(all_results)

    impact = {}

    for feature in Features:
        # Find configs with and without this feature
        with_feature = []
        without_feature = []

        for config_key, results in grouped.items():
            config_set = set(config_key)
            if feature in config_set:
                with_feature.extend(results)
            else:
                without_feature.extend(results)

        # Calculate win rates
        if with_feature and without_feature:
            with_metrics = calculate_metrics(with_feature)
            without_metrics = calculate_metrics(without_feature)
            impact[feature] = with_metrics.win_rate - without_metrics.win_rate
        else:
            impact[feature] = 0.0

    return impact
