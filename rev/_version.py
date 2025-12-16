"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "f7aaab83699fa57a82ea8f174e92e902e65f6e81"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
