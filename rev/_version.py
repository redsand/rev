"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "0ba2768abd2604589a5c98f81bfe35ae2b0d85e2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
