"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "8d1513f356f540785e69011aea8746e1bfa2032d"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
