"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "b185e62c9de489070a9f7649e661a9691de05566"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
