"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.0"
REV_GIT_COMMIT = "b9ffe95ccd8da94039a3d3daca1dc62633b38b8c"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
