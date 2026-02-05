"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "82e11a0f43f009ea5c36b40f67fc7d5a90294959"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
