"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "3a5eca9c8f851128d1e741e6b0b2aa29f974969f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
