"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "bc16cfabd9198f2dbc0573d40cd53a894c5d1112"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
