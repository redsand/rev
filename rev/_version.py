"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "f05c06803f31e6369e2a8b2ad730d111b690ddad"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
