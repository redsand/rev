"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "b857c952404ccc7174f8c6faca9e919646de0447"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
