"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "31f580dab2e015403bce05f2c7421236be468eed"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
