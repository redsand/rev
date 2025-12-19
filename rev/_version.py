"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "10cf7f3d38dc7e997cf8c7268ef7086343181ac0"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
