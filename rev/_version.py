"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "dbc6a03fdabf6b8d26e608213f52234f16649989"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
