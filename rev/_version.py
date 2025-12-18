"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "bd08ac34532b8a73292e9c7c8b6b7641bb1f9747"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
