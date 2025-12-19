"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "0bd6c5614374b1a5029e6554ea7227e8a775c21f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
