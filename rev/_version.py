"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "e33f47a44f4857d7e6295c7931b17a0c34c8c027"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
