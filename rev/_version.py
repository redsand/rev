"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "937790511b05970aee9597cd81fd3292e4747bd9"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
