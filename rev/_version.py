"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "c628789bdb3c0fa34dca4a6e23648116321887c3"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
