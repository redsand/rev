"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "12cb453aa8bce8fb93067a846e26a26dbbafa22b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
