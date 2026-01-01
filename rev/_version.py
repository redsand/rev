"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "5772a7f4f38f11f2ffb19f23f2b5cf98f547b7d9"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
