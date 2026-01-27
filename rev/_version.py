"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "c6dab8c50131a1be9a588bb93e5238ed967d81d4"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
