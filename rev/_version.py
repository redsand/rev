"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "1b1c0e8781e49bac70016282a6d59abb09de8d58"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
