"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "7468f52593f590732b119b48b2f076cdf0a84c07"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
