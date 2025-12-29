"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "b7b6a7db2e286ee9c7f4949a021920a589bbd39e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
