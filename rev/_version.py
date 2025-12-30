"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "8815a216da2dceb4f16586f64d8f2017008578a2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
