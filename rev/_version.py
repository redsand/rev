"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "8c8a6c0f437a87b4df70b60a83bcc7fd0f0cc325"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
