"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "e4eb5da02e49753b37f46d6f8c61c946ce26f579"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
