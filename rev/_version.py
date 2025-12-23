"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "e9207a1d09bed47a745486b8eba28771a51b6150"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
