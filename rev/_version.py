"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "35b2c00b96a18341b08406ad0f2d199ec871dcb2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
