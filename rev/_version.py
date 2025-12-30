"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "f261474e53fa379955ada3ca1ad56bca853b73e5"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
