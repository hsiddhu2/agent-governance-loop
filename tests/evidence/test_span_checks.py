"""The checks that decide whether a deny was recorded and whether enforcement is safe.

All AWS calls are replaced, so these run without an account. They cover the
cases a live sandbox rarely produces on demand: failed queries, empty lists,
missing spans, policies not yet active.
"""
import json
from unittest import mock

import pytest

import policy_mode
import policy_trace
import spans


def logs_client(statuses, messages):
    """A Logs client whose query moves through `statuses` and returns `messages`."""
    client = mock.Mock()
    client.start_query.return_value = {"queryId": "q"}
    replies = [{"status": s, "results": []} for s in statuses[:-1]]
    replies.append({"status": statuses[-1], "results": [
        [{"field": "@timestamp", "value": "ts"}, {"field": "@message", "value": json.dumps(m)}]
        for m in messages]})
    client.get_query_results.side_effect = replies
    return client


def policy_span(decision, determining):
    return {"@timestamp": "ts", "traceId": "abc", "name": "n", "attributes": {
        "aws.agentcore.policy.authorization_decision": decision,
        "aws.agentcore.policy.determining_policies": determining}}


# spans.query_spans

def test_list_attributes_survive_including_empty():
    msg = {"name": "n", "attributes": {"allowed": ["a", "b"], "denied": []}}
    with mock.patch.object(spans.boto3, "client", return_value=logs_client(["Running", "Complete"], [msg])), \
         mock.patch.object(spans.time, "sleep"):
        found = spans.query_spans("| filter x", start=0, end=1)
    assert found[0]["attributes"] == {"allowed": ["a", "b"], "denied": []}
    assert found[0]["@timestamp"] == "ts"


@pytest.mark.parametrize("status", ["Failed", "Cancelled", "Timeout"])
def test_query_that_does_not_complete_raises(status):
    with mock.patch.object(spans.boto3, "client", return_value=logs_client([status], [])):
        with pytest.raises(RuntimeError):
            spans.query_spans("| filter x", start=0, end=1)


def test_query_reads_whole_span_from_spans_log_group():
    client = logs_client(["Complete"], [])
    with mock.patch.object(spans.boto3, "client", return_value=client):
        spans.query_spans('| filter name = "n"', start=5, end=9, limit=3)
    kw = client.start_query.call_args.kwargs
    assert (kw["logGroupName"], kw["startTime"], kw["endTime"]) == ("aws/spans", 5, 9)
    assert kw["queryString"].startswith("fields @timestamp, @message\n| filter name")
    assert kw["queryString"].endswith("| limit 3")


# policy_trace

def test_trace_passes_on_deny_that_names_its_policy():
    with mock.patch.object(policy_trace, "query_spans", return_value=[policy_span("DENY", ["forbid_x"])]):
        with pytest.raises(SystemExit) as e:
            policy_trace.main(5)
    assert e.value.code == 0


@pytest.mark.parametrize("found", [
    [policy_span("DENY", [])],
    [policy_span("DENY", None)],
    [policy_span("ALLOW", ["permit_x"])],
    [],
])
def test_trace_not_met_without_a_named_deny(found):
    with mock.patch.object(policy_trace, "query_spans", return_value=found):
        with pytest.raises(SystemExit) as e:
            policy_trace.main(5)
    assert e.value.code == 1


# policy_mode.current

def test_current_without_gateway_is_log_only(capsys):
    with mock.patch.object(policy_mode, "find_gateway", return_value=None):
        policy_mode.current()
    assert capsys.readouterr().out.strip() == "LOG_ONLY"


def test_current_reports_live_mode(capsys):
    gw = {"policyEngineConfiguration": {"mode": "ENFORCE"}}
    with mock.patch.object(policy_mode, "find_gateway", return_value=gw):
        policy_mode.current()
    assert capsys.readouterr().out.strip() == "ENFORCE"


def test_current_stops_when_no_engine_attached():
    with mock.patch.object(policy_mode, "find_gateway", return_value={}):
        with pytest.raises(SystemExit) as e:
            policy_mode.current()
    assert "no policy engine" in str(e.value.code)


# policy_mode.check_policies

def engine_with(policies):
    control = mock.Mock()
    control.get_paginator.return_value.paginate.return_value = [{"policies": policies}]
    return control


def test_check_policies_rejects_policy_not_active(tmp_path):
    (tmp_path / "a.cedar").write_text("")
    (tmp_path / "b.cedar").write_text("")
    control = engine_with([{"name": "a", "status": "ACTIVE"}, {"name": "b", "status": "CREATING"}])
    with mock.patch.object(policy_mode, "control", control), \
         mock.patch.object(policy_mode, "POLICY_DIRS", (tmp_path,)):
        with pytest.raises(SystemExit) as e:
            policy_mode.check_policies("engine")
    assert "b" in str(e.value.code)


def test_check_policies_rejects_missing_policy(tmp_path):
    (tmp_path / "a.cedar").write_text("")
    with mock.patch.object(policy_mode, "control", engine_with([])), \
         mock.patch.object(policy_mode, "POLICY_DIRS", (tmp_path,)):
        with pytest.raises(SystemExit) as e:
            policy_mode.check_policies("engine")
    assert "missing ['a']" in str(e.value.code)


def test_check_policies_accepts_all_active(tmp_path):
    (tmp_path / "a.cedar").write_text("")
    with mock.patch.object(policy_mode, "control", engine_with([{"name": "a", "status": "ACTIVE"}])), \
         mock.patch.object(policy_mode, "POLICY_DIRS", (tmp_path,)):
        policy_mode.check_policies("engine")


# policy_mode.check

def run_check(listing_span):
    gw = {"gatewayId": "g", "policyEngineConfiguration": {"arn": "arn:x/engine-1", "mode": "LOG_ONLY"}}
    with mock.patch.object(policy_mode, "find_gateway", return_value=gw), \
         mock.patch.object(policy_mode, "check_policies"), \
         mock.patch.object(policy_mode, "cfn_outputs", return_value={"GatewayUrl": "u"}), \
         mock.patch.object(policy_mode, "gateway_token", return_value="tok"), \
         mock.patch.object(policy_mode, "mcp_call", return_value=(200, {})), \
         mock.patch.object(policy_mode, "latest_listing_span", return_value=listing_span), \
         mock.patch.object(policy_mode, "SPAN_WAIT_SECONDS", 0.01), \
         mock.patch.object(policy_mode.time, "sleep"):
        policy_mode.check()


def test_check_refuses_when_nothing_is_allowed():
    with pytest.raises(SystemExit) as e:
        run_check({"time": "ts", "mode": "LOG_ONLY", "allowed": [], "denied": ["a"]})
    assert "allows no tools" in str(e.value.code)


def test_check_refuses_when_no_span_arrives():
    with pytest.raises(SystemExit) as e:
        run_check(None)
    assert "no policy span" in str(e.value.code)


def test_check_ready_when_a_tool_is_allowed(capsys):
    run_check({"time": "ts", "mode": "LOG_ONLY", "allowed": ["a"], "denied": []})
    assert "READY" in capsys.readouterr().out
