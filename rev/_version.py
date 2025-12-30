"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "d193efd44eadd454a165030c30003f0aae104f74"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
