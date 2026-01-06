"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "9930674e82d07356dd0818658aa193147f3aac54"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
