"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "b1ee6e08bdd030af76aa45d2331b6b795fd8d782"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
