"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "59b578925fa681345a1c2dce6e21680deaf7c40d"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
