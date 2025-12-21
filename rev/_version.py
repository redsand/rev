"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "d2b5fb06d69d3c2a54e59468f624e084e053bb32"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
