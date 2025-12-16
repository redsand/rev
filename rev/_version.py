"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "f89f728bf45778d5caaae27e8b2c61b814983e73"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
