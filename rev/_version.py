"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "87c2953cb3226d8dab321a3a6f10ea98ef6275a6"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
