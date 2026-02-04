"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "2880210dabe088e3a246720ec6a1a6fc72940b16"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
