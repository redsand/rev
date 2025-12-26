from rev.execution import quick_verify


def test_extract_error_uses_specific_hint_for_missing_script():
    res = {
        "rc": 1,
        "stdout": "",
        "stderr": "npm error Missing script: \"test\"",
        "error": "",
    }

    msg = quick_verify._extract_error(res)
    assert "Missing test script" in msg
    assert "Analyze the output above" not in msg


def test_extract_error_uses_generic_hint_when_unknown():
    res = {
        "rc": 1,
        "stdout": "",
        "stderr": "Something failed without a known pattern",
        "error": "",
    }

    msg = quick_verify._extract_error(res)
    assert "Analyze the output above" in msg
