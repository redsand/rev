"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "f2152250927add4d7f664dad71afc6935e215a68"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
