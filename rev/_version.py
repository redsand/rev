"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "3705243a3c1ff17d715fb50df8c9c3c4f11c7488"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
