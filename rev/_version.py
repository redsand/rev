"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "adabbd84ed1e8ebe67664e981269a4e2a24f1437"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
