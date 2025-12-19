"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "eb4af83e47dcf4de064cfff1a273f0d444661c9d"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
