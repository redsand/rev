"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "b2f06434df3c673b0ef65f5791fa6792ee822c72"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
