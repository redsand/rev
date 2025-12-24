"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "e253d3ba4f9427544499c99cb9957a7d67126881"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
