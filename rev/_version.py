"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "8b3e7f0753cd46186c3164c92cd2ac720f1d4eac"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
