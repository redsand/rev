"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "405b0020cada291084f4f7bdcf39fa8b0f4def1a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
