"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "78cd55c6cd6bee65bc2214a344f43346cf84349f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
