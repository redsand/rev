"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "8481bb588655016d29c110fbccfcd552d411481c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
