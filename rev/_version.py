"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "a0d6a2c88f5dcec7a56ca9eb51d02f5ff7f34bdc"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
