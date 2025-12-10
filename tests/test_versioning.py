from rev import config
from rev._version import REV_VERSION
from rev.versioning import _version_from_setup, build_version_output, get_version


def test_get_version_matches_setup_and_constant():
    version = get_version()
    assert version == REV_VERSION

    setup_version = _version_from_setup()
    if setup_version:
        assert setup_version == REV_VERSION


def test_build_version_output_uses_package_version():
    system_info = config.get_system_info_cached()
    output = build_version_output(config.OLLAMA_MODEL, system_info)
    assert f"Version:          {REV_VERSION}" in output
