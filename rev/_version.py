"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "9154443725f73941fb92b70f1174f7180da89d29"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
