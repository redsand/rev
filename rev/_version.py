"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "f882e6c116e42586bb0941fd7474e352998be303"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
