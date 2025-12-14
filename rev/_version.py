"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "4c55958d0b1897ed1167d4f7f72221dd24050f3e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
