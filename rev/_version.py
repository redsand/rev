"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "ec98283de9df1705911508553f85d71a01ed7e15"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
