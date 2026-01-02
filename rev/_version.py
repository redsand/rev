"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "ea816d49630cb9f54b83ea914a7369d49aba3cf5"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
