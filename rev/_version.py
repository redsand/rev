"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "06b065aec44f538b7f79736265db99c7b43a0ce2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
