"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "ebb7bb23f88ea19c0fa1fb198c1b0a38b6d2bfa7"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
