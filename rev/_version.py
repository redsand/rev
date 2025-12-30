"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "a4e3ce21bb7168d31a268dec0f285e7cde42b5f0"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
