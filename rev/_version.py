"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "bcd54ddcde2e6939836ad709c2f187448d16d6cf"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
