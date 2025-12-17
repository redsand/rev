"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "dd946696e68ada22c27d7ee049616c331c839d69"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
