"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "654cc5ddf319b22e1f7fad4d87e546b6ac916fe6"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
