"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "11640dd0244ad8254c5c3ee9dec2aa69cd3017bd"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
