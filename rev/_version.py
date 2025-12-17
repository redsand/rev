"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "5b70e88a24c1cf5ccd2a36724daa21894dfbb221"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
