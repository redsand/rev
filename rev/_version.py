"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "20a7d4ad0045926e61a05ae264ffa27e3e3bbb63"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
