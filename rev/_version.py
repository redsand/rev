"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.0.1"
REV_GIT_COMMIT = "0d1203de06fab1cbac95268250fbf372ded597b5"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
