"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "9229e5eca3a584a1f493f1c47a92bafae9cdfce0"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
