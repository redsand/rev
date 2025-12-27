from rev.execution.session import SessionTracker


def test_session_tracker_initializes_lock() -> None:
    tracker = SessionTracker(session_id="test")
    assert hasattr(tracker, "_lock")
