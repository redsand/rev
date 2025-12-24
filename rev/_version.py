"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "c2baa3d2e3ffc2e39570527201cd70a222b8cfe8"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
