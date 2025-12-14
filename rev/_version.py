"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "72af4d1a1b2f163ca789721d312811c892024d6d"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
