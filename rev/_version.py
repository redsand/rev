"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "dc9aeded73642ee4cb229b96fb4f163b0346bd3e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
