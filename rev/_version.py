"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "6a1336f4ad99e894f007b2f4b358b2f170fc3283"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
