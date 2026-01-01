"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "52ee9885a89b0efcbe3d2d4f0af881019cfd817b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
