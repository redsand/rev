"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "c6518e8098e95b97db66de76e66715b3e12e1fba"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
