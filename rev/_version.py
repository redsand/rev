"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "3d3a5ecbf1919355a88183960f76eb5e6fd7621f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
