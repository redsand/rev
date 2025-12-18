"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "941581c3e17b674d8b7860fcfbc1c90130ba3fc2"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
