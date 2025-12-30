"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "ab7b580abdf3284b76ff51a1d7347cef9abd5198"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
