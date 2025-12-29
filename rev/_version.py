"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "c303e8c58e1693e40dfa4a1aa00358dce96a5022"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
