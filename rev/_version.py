"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "8fa957f10fb77863b133124ac11b74251193c9d8"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
