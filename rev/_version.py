"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "767d24b3830e8a8052bc451352a0a508ff004dd9"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
