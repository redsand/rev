"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "7ebf3def5567334955f9660a141058a939af2fcf"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
