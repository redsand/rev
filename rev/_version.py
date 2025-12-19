"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "0faa9f6f54a8b6d5f363768e0b74d4e1a0cb2f4e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
