"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "bdb69ca46ec8bd4dcc6e7033814177e7063fe1e4"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
