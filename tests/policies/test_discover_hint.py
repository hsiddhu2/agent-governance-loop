"""What discovery says when the Gateway does not list a schema tool."""
from discover_tools import kept_from_last_run, missing_tools_message


def test_enforce_points_to_log_only():
    msg = missing_tools_message(["new_tool"], "ENFORCE")
    assert "new_tool" in msg
    assert "make log-only" in msg


def test_log_only_reports_missing_tools_only():
    msg = missing_tools_message(["new_tool"], "LOG_ONLY")
    assert "new_tool" in msg
    assert "make log-only" not in msg


PREVIOUS = {"list_env": "ops___list_env", "purge_claims": "ops___purge_claims"}


def test_enforce_keeps_a_hidden_tool_from_the_last_run():
    kept = kept_from_last_run(["purge_claims"], {"list_env": "ops___list_env"}, PREVIOUS, "ENFORCE")
    assert kept == {"purge_claims": "ops___purge_claims"}


def test_a_tool_never_discovered_is_not_guessed():
    assert kept_from_last_run(["new_tool"], {"list_env": "ops___list_env"}, PREVIOUS, "ENFORCE") is None


def test_a_changed_prefix_drops_the_last_run():
    assert kept_from_last_run(["purge_claims"], {"list_env": "ops2___list_env"}, PREVIOUS, "ENFORCE") is None


def test_outside_enforce_nothing_is_kept():
    assert kept_from_last_run(["purge_claims"], {"list_env": "ops___list_env"}, PREVIOUS, "LOG_ONLY") is None


def test_nothing_listed_proves_nothing():
    assert kept_from_last_run(["purge_claims"], {}, PREVIOUS, "ENFORCE") is None
