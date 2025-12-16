"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "2f6e3172d9b119a47f639a20f85e0d79baeee876"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
