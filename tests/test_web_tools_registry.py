from rev.tools import registry


def test_web_tools_registered():
    tools = {t["function"]["name"] for t in registry.get_available_tools()}
    for name in ("web_search", "fetch_url", "find_files"):
        assert name in tools

