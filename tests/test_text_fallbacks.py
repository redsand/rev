import json

from rev.execution import executor


def test_text_fallbacks_skip_for_review_tasks(monkeypatch):
    calls = []

    def fake_execute_tool(tool_name, tool_args):
        calls.append((tool_name, tool_args))
        return json.dumps({"success": True})

    monkeypatch.setattr(executor, "execute_tool", fake_execute_tool)

    messages = []
    content = """```diff
diff --git a/lib/analysts.py b/lib/analysts.py
index 0000000..1111111 100644
--- a/lib/analysts.py
+++ b/lib/analysts.py
@@ -1 +1 @@
-x=1
+x=2
```"""

    applied = executor._apply_text_fallbacks(content, "review", messages, None, None, None)
    assert applied is False
    assert calls == []


def test_text_fallbacks_accept_codex_patch_format(monkeypatch):
    calls = []

    def fake_execute_tool(tool_name, tool_args):
        calls.append((tool_name, tool_args))
        return json.dumps({"success": True})

    monkeypatch.setattr(executor, "execute_tool", fake_execute_tool)

    messages = []
    content = """*** Begin Patch
*** Update File: lib/analysts.py
@@
-x=1
+x=2
*** End Patch"""

    applied = executor._apply_text_fallbacks(content, "edit", messages, None, None, None)
    assert applied is True
    assert calls and calls[0][0] == "apply_patch"


def test_text_fallbacks_apply_unified_diff_in_edit_tasks(monkeypatch):
    calls = []

    def fake_execute_tool(tool_name, tool_args):
        calls.append((tool_name, tool_args))
        return json.dumps({"success": True})

    monkeypatch.setattr(executor, "execute_tool", fake_execute_tool)

    messages = []
    content = """```diff
diff --git a/lib/analysts.py b/lib/analysts.py
index 0000000..1111111 100644
--- a/lib/analysts.py
+++ b/lib/analysts.py
@@ -1 +1 @@
-x=1
+x=2
```"""

    applied = executor._apply_text_fallbacks(content, "edit", messages, None, None, None)
    assert applied is True
    assert calls and calls[0][0] == "apply_patch"
