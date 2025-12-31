"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "f384f756fec139b7e2c88b5201ad0a114eb82e45"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
