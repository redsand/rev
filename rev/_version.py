"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "6b3ef43cc1ed309cd2bfd7d1964d17ac9d062203"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
