"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "60b634781b3464d318505c4aeb923f48cbcd2342"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
