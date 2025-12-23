"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "b91bbb94d22d96b04d3ccbb94087cce6e447c674"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
