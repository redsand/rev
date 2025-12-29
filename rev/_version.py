"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "bef74947315f51eae14f5d0f2b13a473c4e3137f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
