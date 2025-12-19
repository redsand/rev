"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "1470cf7b8fa8f95d1bd17d461ff5c575f3aa375a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
