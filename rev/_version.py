"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "a83e7c1e218e0cf0cec325456c0e60938cff9df9"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
