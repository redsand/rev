import json

from rev.llm.tool_call_parser import parse_tool_calls_from_text


def test_recover_tool_call_from_json_code_block():
    content = """Here is a tool call:
```json
{"name": "read_file", "arguments": {"path": "foo.txt"}}
```
"""
    calls, cleaned, errors = parse_tool_calls_from_text(content)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "read_file"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["path"] == "foo.txt"
    assert "read_file" not in cleaned  # code block removed
    assert errors == []


def test_recover_multiple_tool_calls_inline_json():
    content = 'First {"name":"one","arguments":{"a":1}} and second {"name":"two","arguments":{"b":2}}'
    calls, cleaned, errors = parse_tool_calls_from_text(content)
    assert len(calls) == 2
    names = {c["function"]["name"] for c in calls}
    assert names == {"one", "two"}
    assert "arguments" not in cleaned  # stripped from content
    assert errors == []


def test_recover_tool_call_from_xml():
    content = "<tool_call><do_thing><param>value</param></do_thing></tool_call>"
    calls, cleaned, errors = parse_tool_calls_from_text(content)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "do_thing"
    args = json.loads(calls[0]["function"]["arguments"])
    assert args["param"] == "value"
    assert "<tool_call>" not in cleaned
    assert errors == []


def test_malformed_json_records_error_but_no_crash():
    content = '{"name": "bad", "arguments": "not-an-object"}'
    calls, cleaned, errors = parse_tool_calls_from_text(content)
    # No valid call, but also no exception
    assert calls == []
    assert isinstance(errors, list)
