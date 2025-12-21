"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "bb92eb7eecf8a928a508ac45033bb2331979ea70"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
