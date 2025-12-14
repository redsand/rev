"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "3fc04fb93f4e306e5634143b93fcc395211d13df"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
