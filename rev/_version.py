"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "5e5558fc57ad748d3c5bc5cec0e6219328bb3711"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
