"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "17d4ce90f5e9c33d9d291647fa60e0bebd069e3b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
