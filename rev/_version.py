"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "205f9c8471df8d73ccf7693cc33e89c03c17ef5d"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
