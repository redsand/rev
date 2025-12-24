"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "58688e7e27219d26802c57ce041ed96c156dcc26"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
