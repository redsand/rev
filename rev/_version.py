"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "d3af9c36995be412870242c7384eb2b953f3d37a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
