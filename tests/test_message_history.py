from rev.execution import executor


def test_trim_history_with_notice_emits_message(capsys):
    messages = [{"role": "system", "content": "system"}]
    for idx in range(25):
        messages.append({"role": "user", "content": f"msg-{idx}"})

    trimmed, trimmed_flag = executor._trim_history_with_notice(messages, max_recent=20)

    assert trimmed_flag is True
    assert len(trimmed) == 22
    assert trimmed[1]["content"].startswith("[Summary of previous work]")

    captured = capsys.readouterr().out
    assert "Context window trimmed" in captured
    assert "26 → 22" in captured
    assert "keeping last 20" in captured
