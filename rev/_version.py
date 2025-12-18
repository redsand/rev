"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "77186f8375955ba00c661d350e4c309511d0b392"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
