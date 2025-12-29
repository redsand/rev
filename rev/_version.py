"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "65eab338b7e2274915d59b49371234b2a70057f9"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
