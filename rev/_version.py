"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "17e33e3faf1f551f0171699e5323c473caf7f53a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
