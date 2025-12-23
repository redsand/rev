"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "bb72252f258f10062deddab90e4070c5ed8ea339"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
