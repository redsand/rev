"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "be3a22bd4b96f334b167271efb86b3eae50a5285"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
