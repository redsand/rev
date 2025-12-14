"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "a78913f6a0c0beb906fb70551419e6911c510d7b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
