"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "eb111522a39b15ceae635a9c6c6d32f4c665a2fa"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
