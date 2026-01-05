"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "db4ebd00f4e32fe9c1463df8051f6a0e075814db"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
