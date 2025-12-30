"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "1c22b1a3b231e3e39d59f16caead68538be8c5a0"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
