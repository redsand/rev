"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "1151128bd4cd200b4101469d03957ab737e8e60f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
