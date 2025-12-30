"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "4bc9cc7f5d5b4692f2bc0c7b20a6ebf43c68c12c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
