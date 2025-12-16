"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "9d325d516007fb027c1b1040516c6f0de50dc5de"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
