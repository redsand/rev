"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "a6bccf632be170a2b21bf14700f9e091cbfea1f3"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
