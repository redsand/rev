"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "5f0799542c13f274c72b7f19ffc5aa10666dbc34"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
