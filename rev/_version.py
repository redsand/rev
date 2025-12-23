"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "68f3ff03112b0b43aecd93f2cd99b9355c41dc84"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
