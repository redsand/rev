"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "7f27cf6fbd477f29ff61986c47597ffdd3137a69"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
