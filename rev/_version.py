"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "09e3ee1f267f5dd14d13b3285f4e6cfa950d202c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
