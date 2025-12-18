"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "88e91c21f9bad024326a11282db69ae2763e7d57"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
