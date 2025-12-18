"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "bbb40b24354015c60eeb73c26e717178ba16f1f6"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
