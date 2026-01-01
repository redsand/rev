"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "936f16ae5a1a0d6cf5a857d064b0505c2e78bf1e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
