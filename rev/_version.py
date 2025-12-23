"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "5d5121b0a1f43205b5b39cbbdbbe87036d794bb7"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
