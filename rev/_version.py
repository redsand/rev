"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "b70294b78a9e837597d696db28f6adbceeea19ec"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
