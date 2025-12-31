"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "3802d0d507320dcec6e4812ec39325ef7ef3f7eb"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
