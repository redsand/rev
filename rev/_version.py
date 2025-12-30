"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "d9df657475012d3d42a3a782f2e4b3ed8026338c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
