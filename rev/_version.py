"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "21b51f7f138f2ad02b03b2311744f48ecb14763e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
