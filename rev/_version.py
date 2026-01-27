"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "5c669f7a860eb5d2f894aa26fcde4c565d8fa4a2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
