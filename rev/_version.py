"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "1263151e99955726a2a0fb4e071cdc5ef813a146"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
