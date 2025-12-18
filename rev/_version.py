"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "520e30d1d362a691d62eb56d007ad4e468e3a69b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
