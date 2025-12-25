"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "e71a7a63fcf6a104240e31572275a83636d5d954"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
