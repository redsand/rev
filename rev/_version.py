"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "a6c069faf45149222e7de4a8efacee11846c7196"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
