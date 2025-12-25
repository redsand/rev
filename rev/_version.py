"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "24d7860a2d0116cf7bc2e8dee56fdbecae0a8be1"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
