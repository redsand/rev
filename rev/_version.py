"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "1829b920b4838a51f637db80402d7cd2bc3a72d4"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
