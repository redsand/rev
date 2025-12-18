"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "e8a429bcb9fd1e37c0ae627b193646ad2f68d9d8"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
