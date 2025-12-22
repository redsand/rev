#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for ablation mode and benchmarking."""

import pytest
from pathlib import Path
import tempfile
import json

from rev.ablation.feature_flags import (
    Features,
    FeatureRegistry,
    AblationConfig,
    create_baseline_config,
    create_full_config,
    create_custom_config,
)
from rev.ablation.benchmark import (
    BenchmarkTask,
    BenchmarkResult,
    BenchmarkRunner,
    load_tasks_from_directory,
)
from rev.ablation.metrics import (
    AblationMetrics,
    calculate_metrics,
    compare_configs,
    group_results_by_config,
    find_best_config,
    feature_impact_analysis,
)


class TestFeatureFlags:
    """Test feature flag system."""

    def teardown_method(self):
        """Clean up after each test."""
        FeatureRegistry.clear()

    def test_default_all_enabled(self):
        """Verify all features enabled by default."""
        assert FeatureRegistry.is_enabled(Features.ANCHORING)
        assert FeatureRegistry.is_enabled(Features.DEBATE)
        assert FeatureRegistry.is_enabled(Features.JUDGE)

    def test_baseline_config(self):
        """Verify baseline config disables advanced features."""
        config = create_baseline_config("test_001", "test_suite")
        FeatureRegistry.set_config(config)

        assert FeatureRegistry.is_enabled(Features.BASELINE)
        assert not FeatureRegistry.is_enabled(Features.ANCHORING)
        assert not FeatureRegistry.is_enabled(Features.DEBATE)

    def test_full_config(self):
        """Verify full config enables all features."""
        config = create_full_config("test_002", "test_suite")
        FeatureRegistry.set_config(config)

        assert FeatureRegistry.is_enabled(Features.BASELINE)
        assert FeatureRegistry.is_enabled(Features.ANCHORING)
        assert FeatureRegistry.is_enabled(Features.DEBATE)
        assert FeatureRegistry.is_enabled(Features.JUDGE)

    def test_custom_config(self):
        """Verify custom config with specific features."""
        config = create_custom_config(
            "test_003",
            "test_suite",
            {Features.ANCHORING, Features.MEMORY}
        )
        FeatureRegistry.set_config(config)

        assert FeatureRegistry.is_enabled(Features.ANCHORING)
        assert FeatureRegistry.is_enabled(Features.MEMORY)
        assert not FeatureRegistry.is_enabled(Features.DEBATE)
        assert not FeatureRegistry.is_enabled(Features.JUDGE)

    def test_get_enabled_features(self):
        """Verify getting enabled features."""
        config = create_custom_config(
            "test_004",
            "test_suite",
            {Features.ANCHORING, Features.DEBATE}
        )
        FeatureRegistry.set_config(config)

        enabled = FeatureRegistry.get_enabled_features()
        assert Features.ANCHORING in enabled
        assert Features.DEBATE in enabled
        assert Features.JUDGE not in enabled

    def test_get_disabled_features(self):
        """Verify getting disabled features."""
        config = create_baseline_config("test_005", "test_suite")
        FeatureRegistry.set_config(config)

        disabled = FeatureRegistry.get_disabled_features()
        assert Features.ANCHORING in disabled
        assert Features.DEBATE in disabled

    def test_clear_config(self):
        """Verify clearing config returns to default."""
        config = create_baseline_config("test_006", "test_suite")
        FeatureRegistry.set_config(config)
        assert not FeatureRegistry.is_enabled(Features.ANCHORING)

        FeatureRegistry.clear()
        assert FeatureRegistry.is_enabled(Features.ANCHORING)


class TestBenchmarkTask:
    """Test benchmark task structure."""

    def test_create_task(self):
        """Verify task creation."""
        task = BenchmarkTask(
            name="Test Task",
            description="A test task",
            initial_files={"test.py": "print('hello')"},
            user_request="Fix the code",
            success_criteria=["Code works"],
            expected_files=["test.py"]
        )

        assert task.name == "Test Task"
        assert task.timeout_seconds == 300  # default

    def test_task_validation(self):
        """Verify task validation."""
        with pytest.raises(ValueError):
            BenchmarkTask(
                name="",  # Empty name
                description="A test task",
                initial_files={},
                user_request="Fix the code",
                success_criteria=["Works"],
                expected_files=[]
            )


class TestBenchmarkResult:
    """Test benchmark result structure."""

    def test_result_serialization(self):
        """Verify result can be serialized/deserialized."""
        result = BenchmarkResult(
            task_name="Test Task",
            feature_config={Features.ANCHORING, Features.DEBATE},
            success=True,
            time_seconds=45.2,
            iterations=5,
            loops_avoided=1,
            tokens_used=1200,
            artifacts_created=["test.py"],
            error_message=None
        )

        # Convert to dict
        data = result.to_dict()
        assert data["task_name"] == "Test Task"
        assert "anchoring" in data["feature_config"]

        # Convert back
        restored = BenchmarkResult.from_dict(data)
        assert restored.task_name == result.task_name
        assert restored.success == result.success
        assert Features.ANCHORING in restored.feature_config


class TestBenchmarkRunner:
    """Test benchmark runner."""

    def test_runner_creation(self):
        """Verify runner can be created."""
        tasks = [
            BenchmarkTask(
                name="Task 1",
                description="Test",
                initial_files={},
                user_request="Test",
                success_criteria=["Works"],
                expected_files=[]
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(tasks, Path(tmpdir))
            assert len(runner.tasks) == 1
            assert runner.output_dir.exists()

    def test_save_and_load_results(self):
        """Verify results can be saved and loaded."""
        tasks = []
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = BenchmarkRunner(tasks, Path(tmpdir))

            # Add a result
            result = BenchmarkResult(
                task_name="Test",
                feature_config={Features.BASELINE},
                success=True,
                time_seconds=10.0,
                iterations=3,
                loops_avoided=0,
                tokens_used=500,
                artifacts_created=[]
            )
            runner.results.append(result)

            # Save results
            output_path = runner.save_results("test.json")
            assert output_path.exists()

            # Load results
            runner2 = BenchmarkRunner([], Path(tmpdir))
            loaded = runner2.load_results(output_path)
            assert len(loaded) == 1
            assert loaded[0].task_name == "Test"


class TestMetrics:
    """Test metrics calculation."""

    def test_calculate_metrics(self):
        """Verify metrics calculation."""
        results = [
            BenchmarkResult(
                task_name="Task 1",
                feature_config={Features.ANCHORING},
                success=True,
                time_seconds=10.0,
                iterations=5,
                loops_avoided=1,
                tokens_used=1000,
                artifacts_created=[]
            ),
            BenchmarkResult(
                task_name="Task 2",
                feature_config={Features.ANCHORING},
                success=False,
                time_seconds=20.0,
                iterations=10,
                loops_avoided=2,
                tokens_used=2000,
                artifacts_created=[]
            )
        ]

        metrics = calculate_metrics(results)
        assert metrics.win_rate == 0.5  # 1/2 success
        assert metrics.avg_time_seconds == 15.0  # (10+20)/2
        assert metrics.avg_iterations == 7.5  # (5+10)/2
        assert metrics.avg_tokens == 1500.0  # (1000+2000)/2
        assert metrics.num_tasks == 2

    def test_calculate_metrics_empty(self):
        """Verify metrics with no results."""
        metrics = calculate_metrics([])
        assert metrics.win_rate == 0.0
        assert metrics.num_tasks == 0

    def test_compare_configs(self):
        """Verify config comparison."""
        baseline = AblationMetrics(
            feature_config={Features.BASELINE},
            win_rate=0.6,
            avg_time_seconds=100.0,
            avg_iterations=10,
            avg_loops_avoided=1,
            avg_tokens=2000,
            num_tasks=10
        )

        experimental = AblationMetrics(
            feature_config={Features.ANCHORING, Features.DEBATE},
            win_rate=0.8,
            avg_time_seconds=90.0,
            avg_iterations=8,
            avg_loops_avoided=2,
            avg_tokens=1800,
            num_tasks=10
        )

        report = compare_configs(baseline, experimental)
        assert "COMPARISON REPORT" in report
        assert "+20.0%" in report or "+0.2" in report  # Win rate improvement

    def test_group_results_by_config(self):
        """Verify grouping by config."""
        results = [
            BenchmarkResult(
                task_name="Task 1",
                feature_config={Features.ANCHORING},
                success=True,
                time_seconds=10.0,
                iterations=5,
                loops_avoided=0,
                tokens_used=1000,
                artifacts_created=[]
            ),
            BenchmarkResult(
                task_name="Task 2",
                feature_config={Features.ANCHORING},
                success=True,
                time_seconds=10.0,
                iterations=5,
                loops_avoided=0,
                tokens_used=1000,
                artifacts_created=[]
            ),
            BenchmarkResult(
                task_name="Task 3",
                feature_config={Features.DEBATE},
                success=True,
                time_seconds=10.0,
                iterations=5,
                loops_avoided=0,
                tokens_used=1000,
                artifacts_created=[]
            )
        ]

        grouped = group_results_by_config(results)
        assert len(grouped) == 2  # Two different configs

    def test_find_best_config(self):
        """Verify finding best config."""
        results = [
            BenchmarkResult(
                task_name="Task 1",
                feature_config={Features.BASELINE},
                success=False,
                time_seconds=10.0,
                iterations=5,
                loops_avoided=0,
                tokens_used=1000,
                artifacts_created=[]
            ),
            BenchmarkResult(
                task_name="Task 2",
                feature_config={Features.ANCHORING},
                success=True,
                time_seconds=10.0,
                iterations=5,
                loops_avoided=0,
                tokens_used=1000,
                artifacts_created=[]
            )
        ]

        best = find_best_config(results)
        assert Features.ANCHORING in best


class TestTaskLoading:
    """Test loading tasks from files."""

    def test_load_tasks_from_directory(self):
        """Verify loading tasks from YAML files."""
        # Test with actual benchmark tasks directory
        tasks_dir = Path("benchmarks/tasks")
        if tasks_dir.exists():
            tasks = load_tasks_from_directory(tasks_dir)
            assert len(tasks) > 0
            assert all(isinstance(t, BenchmarkTask) for t in tasks)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
