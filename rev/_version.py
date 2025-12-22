"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "9f505560572bdc165db5cb8a249a3b574155d43e"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
