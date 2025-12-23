"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "2eec9faf06b7a25da4c09272ee55443369df218e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
