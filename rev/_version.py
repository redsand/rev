"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "0ba7725923fabc2cff5383e2179d7cbe0ee2e5d3"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
