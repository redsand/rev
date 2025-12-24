"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "c4ed26f444f445ea784f4e8bc3bb39d00a396c19"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
