#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark harness for ablation experiments.

This module provides the infrastructure for running controlled
experiments to measure the impact of different features.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from rev.ablation.feature_flags import Features, AblationConfig, FeatureRegistry
from rev.debug_logger import get_logger


logger = get_logger()


@dataclass
class BenchmarkTask:
    """A task for benchmarking.

    This represents a single coding task that the agent should complete.
    Tasks are defined declaratively to ensure reproducibility.
    """
    name: str
    description: str
    initial_files: Dict[str, str]  # filename -> content
    user_request: str
    success_criteria: List[str]  # List of criteria that must be met
    expected_files: List[str]  # Files that should exist after completion
    timeout_seconds: int = 300

    def __post_init__(self):
        """Validate task definition."""
        if not self.name:
            raise ValueError("Task name must be non-empty")
        if not self.user_request:
            raise ValueError("Task must have a user request")
        if not self.success_criteria:
            raise ValueError("Task must have at least one success criterion")


@dataclass
class BenchmarkResult:
    """Result from running a single task."""
    task_name: str
    feature_config: Set[Features]
    success: bool
    time_seconds: float
    iterations: int  # How many LLM calls
    loops_avoided: int  # Detected retry loops
    tokens_used: int
    artifacts_created: List[str]
    error_message: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "task_name": self.task_name,
            "feature_config": [f.value for f in self.feature_config],
            "success": self.success,
            "time_seconds": self.time_seconds,
            "iterations": self.iterations,
            "loops_avoided": self.loops_avoided,
            "tokens_used": self.tokens_used,
            "artifacts_created": self.artifacts_created,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: Dict) -> 'BenchmarkResult':
        """Create from dictionary."""
        return BenchmarkResult(
            task_name=data["task_name"],
            feature_config={Features(f) for f in data["feature_config"]},
            success=data["success"],
            time_seconds=data["time_seconds"],
            iterations=data["iterations"],
            loops_avoided=data["loops_avoided"],
            tokens_used=data["tokens_used"],
            artifacts_created=data["artifacts_created"],
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )


class BenchmarkRunner:
    """Runner for benchmark experiments.

    This class handles setting up tasks, running them with different
    feature configurations, and collecting results.
    """

    def __init__(self, tasks: List[BenchmarkTask], output_dir: Optional[Path] = None):
        """Initialize benchmark runner.

        Args:
            tasks: List of tasks to run
            output_dir: Directory for results (default: ./benchmark_results)
        """
        self.tasks = tasks
        self.output_dir = output_dir or Path("benchmark_results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[BenchmarkResult] = []

    def run_ablation(
        self,
        feature_configs: List[Set[Features]],
        run_id_prefix: str = "exp"
    ) -> List[BenchmarkResult]:
        """Run all tasks with each feature configuration.

        Args:
            feature_configs: List of feature sets to test
            run_id_prefix: Prefix for run IDs

        Returns:
            List of all benchmark results
        """
        all_results = []

        for config_idx, features in enumerate(feature_configs):
            logger.log("benchmark", "CONFIG_START", {
                "config_idx": config_idx,
                "features": [f.value for f in features],
                "num_tasks": len(self.tasks)
            }, "INFO")

            # Create ablation config
            ablation_config = AblationConfig(
                enabled_features=features,
                run_id=f"{run_id_prefix}_{config_idx:03d}",
                benchmark_name="standard_suite"
            )

            # Set global config
            FeatureRegistry.set_config(ablation_config)

            # Run all tasks with this config
            for task in self.tasks:
                logger.log("benchmark", "TASK_START", {
                    "task": task.name,
                    "config": ablation_config.run_id
                }, "INFO")

                result = self._run_single_task(task, features)
                all_results.append(result)
                self.results.append(result)

                logger.log("benchmark", "TASK_COMPLETE", {
                    "task": task.name,
                    "success": result.success,
                    "time": result.time_seconds
                }, "INFO")

            # Clear config after this run
            FeatureRegistry.clear()

            logger.log("benchmark", "CONFIG_COMPLETE", {
                "config_idx": config_idx,
                "features": [f.value for f in features]
            }, "INFO")

        return all_results

    def _run_single_task(
        self,
        task: BenchmarkTask,
        features: Set[Features]
    ) -> BenchmarkResult:
        """Run a single task with feature configuration.

        Args:
            task: The task to run
            features: Features enabled for this run

        Returns:
            BenchmarkResult with outcome
        """
        # TODO: This is a stub - actual implementation would:
        # 1. Create workspace with initial files
        # 2. Run the agent with the user request
        # 3. Check success criteria
        # 4. Collect metrics
        # 5. Clean up workspace

        start_time = time.time()

        try:
            # Placeholder implementation
            # In real implementation, this would call the executor
            success = False
            iterations = 0
            loops_avoided = 0
            tokens_used = 0
            artifacts_created = []
            error_message = None

            # Simulate task execution
            logger.log("benchmark", "TASK_SIMULATION", {
                "task": task.name,
                "note": "Using placeholder implementation"
            }, "WARNING")

            elapsed_time = time.time() - start_time

            return BenchmarkResult(
                task_name=task.name,
                feature_config=features,
                success=success,
                time_seconds=elapsed_time,
                iterations=iterations,
                loops_avoided=loops_avoided,
                tokens_used=tokens_used,
                artifacts_created=artifacts_created,
                error_message=error_message,
                metadata={
                    "placeholder": True,
                    "timeout": task.timeout_seconds
                }
            )

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.log("benchmark", "TASK_ERROR", {
                "task": task.name,
                "error": str(e)
            }, "ERROR")

            return BenchmarkResult(
                task_name=task.name,
                feature_config=features,
                success=False,
                time_seconds=elapsed_time,
                iterations=0,
                loops_avoided=0,
                tokens_used=0,
                artifacts_created=[],
                error_message=str(e)
            )

    def save_results(self, filename: Optional[str] = None):
        """Save results to JSON file.

        Args:
            filename: Output filename (default: results_<timestamp>.json)
        """
        if filename is None:
            timestamp = int(time.time())
            filename = f"results_{timestamp}.json"

        output_path = self.output_dir / filename

        data = {
            "timestamp": time.time(),
            "num_results": len(self.results),
            "results": [r.to_dict() for r in self.results]
        }

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)

        logger.log("benchmark", "RESULTS_SAVED", {
            "path": str(output_path),
            "num_results": len(self.results)
        }, "INFO")

        return output_path

    def load_results(self, filepath: Path) -> List[BenchmarkResult]:
        """Load results from JSON file.

        Args:
            filepath: Path to results file

        Returns:
            List of BenchmarkResult objects
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        results = [BenchmarkResult.from_dict(r) for r in data["results"]]
        self.results.extend(results)

        logger.log("benchmark", "RESULTS_LOADED", {
            "path": str(filepath),
            "num_results": len(results)
        }, "INFO")

        return results


def load_task_from_yaml(filepath: Path) -> BenchmarkTask:
    """Load a benchmark task from YAML file.

    Args:
        filepath: Path to YAML file

    Returns:
        BenchmarkTask instance
    """
    import yaml

    with open(filepath, 'r') as f:
        data = yaml.safe_load(f)

    return BenchmarkTask(
        name=data["name"],
        description=data["description"],
        initial_files=data.get("initial_files", {}),
        user_request=data["user_request"],
        success_criteria=data["success_criteria"],
        expected_files=data.get("expected_files", []),
        timeout_seconds=data.get("timeout_seconds", 300)
    )


def load_tasks_from_directory(dirpath: Path) -> List[BenchmarkTask]:
    """Load all benchmark tasks from a directory.

    Args:
        dirpath: Directory containing YAML task files

    Returns:
        List of BenchmarkTask instances
    """
    tasks = []
    for yaml_file in sorted(dirpath.glob("*.yaml")):
        try:
            task = load_task_from_yaml(yaml_file)
            tasks.append(task)
            logger.log("benchmark", "TASK_LOADED", {
                "file": yaml_file.name,
                "task": task.name
            }, "DEBUG")
        except Exception as e:
            logger.log("benchmark", "TASK_LOAD_ERROR", {
                "file": yaml_file.name,
                "error": str(e)
            }, "ERROR")

    return tasks
