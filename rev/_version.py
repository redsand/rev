"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "4d8753a6a9621bd42857a9f39acd2dc1877b358d"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
