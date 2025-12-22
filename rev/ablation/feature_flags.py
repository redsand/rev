#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Feature toggle system for ablation experiments.

This module provides a global feature registry that allows components
to check if they're enabled in the current experiment configuration.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set


class Features(Enum):
    """Toggleable features for ablation experiments."""
    BASELINE = "baseline"  # No advanced features
    ANCHORING = "anchoring"  # Anchoring score system
    DEBATE = "debate"  # Debate mode
    JUDGE = "judge"  # Judge agent verification
    MEMORY = "memory"  # Project memory
    DISCRIMINATING_TESTS = "discriminating_tests"  # Discriminating test generation
    RUN_BUNDLE = "run_bundle"  # Replay capability


@dataclass
class AblationConfig:
    """Configuration for ablation experiment."""
    enabled_features: Set[Features]
    run_id: str
    benchmark_name: str

    def __post_init__(self):
        """Validate configuration."""
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        if not self.benchmark_name:
            raise ValueError("benchmark_name must be non-empty")


class FeatureRegistry:
    """Global registry for checking feature flags.

    This is a singleton-like class that maintains the current
    ablation configuration and provides feature checks.

    Usage:
        # At start of experiment
        config = AblationConfig(
            enabled_features={Features.ANCHORING, Features.DEBATE},
            run_id="exp_001",
            benchmark_name="standard_suite"
        )
        FeatureRegistry.set_config(config)

        # In component code
        if FeatureRegistry.is_enabled(Features.ANCHORING):
            # Use anchoring score
            pass
    """

    _config: Optional[AblationConfig] = None

    @classmethod
    def is_enabled(cls, feature: Features) -> bool:
        """Check if a feature is enabled.

        Args:
            feature: The feature to check

        Returns:
            True if feature is enabled, False otherwise.
            If no config is set, all features are enabled by default.
        """
        if cls._config is None:
            # No ablation config = all features enabled
            return True

        return feature in cls._config.enabled_features

    @classmethod
    def set_config(cls, config: Optional[AblationConfig]):
        """Set the ablation configuration.

        Args:
            config: The ablation config, or None to clear
        """
        cls._config = config

    @classmethod
    def get_config(cls) -> Optional[AblationConfig]:
        """Get the current ablation configuration.

        Returns:
            Current config, or None if not set
        """
        return cls._config

    @classmethod
    def clear(cls):
        """Clear the ablation configuration (return to normal mode)."""
        cls._config = None

    @classmethod
    def get_enabled_features(cls) -> Set[Features]:
        """Get set of currently enabled features.

        Returns:
            Set of enabled features, or all features if no config set
        """
        if cls._config is None:
            return set(Features)
        return cls._config.enabled_features

    @classmethod
    def get_disabled_features(cls) -> Set[Features]:
        """Get set of currently disabled features.

        Returns:
            Set of disabled features, or empty set if no config set
        """
        if cls._config is None:
            return set()
        all_features = set(Features)
        return all_features - cls._config.enabled_features


def create_baseline_config(run_id: str, benchmark_name: str) -> AblationConfig:
    """Create baseline configuration (all advanced features disabled).

    Args:
        run_id: Unique identifier for this run
        benchmark_name: Name of the benchmark being run

    Returns:
        AblationConfig with only baseline features
    """
    return AblationConfig(
        enabled_features={Features.BASELINE},
        run_id=run_id,
        benchmark_name=benchmark_name,
    )


def create_full_config(run_id: str, benchmark_name: str) -> AblationConfig:
    """Create full configuration (all features enabled).

    Args:
        run_id: Unique identifier for this run
        benchmark_name: Name of the benchmark being run

    Returns:
        AblationConfig with all features enabled
    """
    return AblationConfig(
        enabled_features=set(Features),
        run_id=run_id,
        benchmark_name=benchmark_name,
    )


def create_custom_config(
    run_id: str,
    benchmark_name: str,
    features: Set[Features]
) -> AblationConfig:
    """Create custom configuration with specific features.

    Args:
        run_id: Unique identifier for this run
        benchmark_name: Name of the benchmark being run
        features: Set of features to enable

    Returns:
        AblationConfig with specified features
    """
    return AblationConfig(
        enabled_features=features,
        run_id=run_id,
        benchmark_name=benchmark_name,
    )
