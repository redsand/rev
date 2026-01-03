"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "ac0988edc6f8fbf27b51000de7927579cc03c488"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
