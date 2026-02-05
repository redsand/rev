"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "af0b52ccefe8f9ea1d422c2aea3b99ae375048d7"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
