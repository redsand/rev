"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "6f90870d2975b85dc395bd2937cca0c5ae556c7c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
