"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "f6ca2c7cd9553a69a87474cb38d2c1813eb97e6b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
