"""What discovery says when the Gateway does not list a schema tool."""
from discover_tools import missing_tools_message


def test_enforce_points_to_log_only():
    msg = missing_tools_message(["new_tool"], "ENFORCE")
    assert "new_tool" in msg
    assert "make log-only" in msg


def test_log_only_reports_missing_tools_only():
    msg = missing_tools_message(["new_tool"], "LOG_ONLY")
    assert "new_tool" in msg
    assert "make log-only" not in msg
