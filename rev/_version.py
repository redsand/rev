"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "7af8a15a7bf9b6b695a2e680ef1569e5a7f59280"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
