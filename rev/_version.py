"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "d5ccea81ad70f8df8d7748d8b47ed57997db0d95"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
