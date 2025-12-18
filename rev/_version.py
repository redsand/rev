"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "1c2f02ab1945464c8ce133bdd471a7bbc6a7b842"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
