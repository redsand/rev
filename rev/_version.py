"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "4e1849d8966b5c7a6e9e3267dcb2801a16f370f1"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
