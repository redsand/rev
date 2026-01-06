"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "eded1616a44e699c959f4ef43d6856de713a6aa4"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
