"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "56a1869139d06a05ae99b12c28ef0f5466255f4f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
