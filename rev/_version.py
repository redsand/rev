"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "794aadd918ce9da3835e9f369fc974b9efc5dc9f"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
