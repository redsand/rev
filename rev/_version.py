"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "031e0977c05457645df90ab14e1a82ffc476192a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
