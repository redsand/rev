"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "4fb660dd11b42add8291b28f01e832679ee98fac"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
