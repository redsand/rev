"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "9a69675a0d3b34aedf8ed74a46ea90703b1181ed"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
