"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "cf55db41c052e65327bb3a7fa4d157cbbca9919e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
