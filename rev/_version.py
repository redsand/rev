"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "d701dabb34e8af85dca7a35844b2c9b661d95b6e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
