"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "e111c50b06d4857b0515938ed2adc0ca8226ecf4"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
