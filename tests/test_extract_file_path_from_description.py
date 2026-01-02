from rev.execution.orchestrator import _extract_file_path_from_description


def test_extract_prefers_full_relative_path():
    desc = "READ inspect src/main.ts to verify router"
    assert _extract_file_path_from_description(desc) == "src/main.ts"


def test_extract_handles_backticked():
    desc = "inspect `src/app.vue` and main"
    assert _extract_file_path_from_description(desc) == "src/app.vue"
