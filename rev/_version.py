"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "4accca173e0f69f2cf64367b8276587a37cfb12c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
