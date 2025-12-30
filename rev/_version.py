"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "79489cba2b3640168ec925a1695c2d841af7e535"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
