"""Centralized version constant for rev."""

# Note: REV_GIT_COMMIT should be populated at build time so wheels/sdists carry
# the commit even when git metadata is unavailable at runtime.
REV_VERSION = "2.1.1"
REV_GIT_COMMIT = "855637c49b34acf49301fd34cf455f692a181e9a"

__all__ = ["REV_VERSION", "REV_GIT_COMMIT"]
