"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "557655969e5aac5d8a23156597d15abd6cec491a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
