"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "bff2226ce918b0fa8f07ae8ed710d2e83665355c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
