"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "a31b21533f512c4ac435e34cc413ecae9778e8b9"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
