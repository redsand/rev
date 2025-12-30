"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "634b2d111f87c7a361c0e1e3c970de0749077165"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
