"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "15f4bdaf89a88b748d7f17b280bb51eba6f10601"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
