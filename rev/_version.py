"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "8ac14c04a349864d19192b1be979a30e5e0f00d2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
