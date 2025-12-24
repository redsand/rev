"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "050152ec3480905aba74c738b1a4393c892fdbbe"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
