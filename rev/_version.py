"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "a99dd2f51b63548f292709562982d08e116d7a72"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
