"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "33a4a2dd883a2bc3bc89528cdd52882cf3c28fd8"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
