"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "ceea40bdc6c8721f3d2422e4ecf4e1873d752534"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
