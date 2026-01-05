"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "0529a3c0bc769da154d0fda2f86318f2ccdfc08f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
