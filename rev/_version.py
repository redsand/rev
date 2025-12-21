"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "635f86aa83f34689c422ba7a4887bb3ada61d3c5"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
