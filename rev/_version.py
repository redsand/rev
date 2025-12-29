"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "45239d410d36adc3f1cd431b33d1a138b1fc112b"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
