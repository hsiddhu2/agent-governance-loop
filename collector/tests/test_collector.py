"""Offline tests. AWS responses are stand-ins shaped like the real ones."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from importlib import resources

import pytest
import yaml

from agentcore_evidence import checks, cli, control_plane, records, report
from agentcore_evidence.redact import Redactor, client_ids

GW_ARN = "arn:aws:bedrock-agentcore:us-east-1:acct:gateway/gw-abc"


def selector(*fields):
    return {"AdvancedEventSelectors": [{"Name": "s", "FieldSelectors": list(fields)}]}


DATA = {"Field": "eventCategory", "Equals": ["Data"]}
GATEWAY = {"Field": "resources.type", "Equals": ["AWS::BedrockAgentCore::Gateway"]}


def test_trail_selecting_every_gateway_counts():
    assert records.selects_gateway(selector(DATA, GATEWAY), GW_ARN)


def test_trail_scoped_to_another_gateway_does_not_count():
    other = {"Field": "resources.ARN", "Equals": [GW_ARN.replace("gw-abc", "gw-xyz")]}
    assert not records.selects_gateway(selector(DATA, GATEWAY, other), GW_ARN)


def test_management_only_trail_does_not_count():
    assert not records.selects_gateway({"EventSelectors": [{"ReadWriteType": "All"}]}, GW_ARN)


def test_log_only_policy_means_not_enforced():
    gw = {"policyEngineConfiguration": {"arn": "arn:x:policy-engine/e1", "mode": "ENFORCE"}}
    e = control_plane.enforcement(gw, [{"name": "a", "enforcementMode": "ACTIVE"},
                                       {"name": "b", "enforcementMode": "LOG_ONLY"}])
    assert not e["enforced"] and e["policiesNotEnforced"] == ["b"]


def test_log_only_engine_means_not_enforced():
    gw = {"policyEngineConfiguration": {"arn": "arn:x:policy-engine/e1", "mode": "LOG_ONLY"}}
    assert not control_plane.enforcement(gw, [{"name": "a", "enforcementMode": "ACTIVE"}])["enforced"]


def span(name, **attributes):
    return {"@message": json.dumps({"name": name, "traceId": "t1", "endTimeUnixNano": "1700000000000000000",
                                    "attributes": attributes})}


def test_decision_is_joined_to_its_tool(monkeypatch):
    rows = [
        span("AgentCore.Policy.AuthorizeAction", **{
            "aws.request.id": "r1", records.DECISION: "DENY",
            "aws.agentcore.policy.determining_policies": ["forbid_purge-1"],
            "aws.agentcore.gateway.policy.mode": "ENFORCE"}),
        span("AgentCore.Gateway.InvokeTool", **{"aws.request.id": "r1", "tool.name": "ops___purge"}),
    ]
    monkeypatch.setattr(records, "run_query", lambda *a: rows)
    d = records.decisions(None, "gw-abc", 0, 1)
    assert d["counts"] == {"DENY": 1}
    [row] = d["decisions"]
    assert row["tool"] == "ops___purge" and row["determiningPolicies"] == ["forbid_purge-1"]


def trail_event(gateway_arn=GW_ARN, error=None):
    body = {"jsonrpc": "2.0", "id": 1}
    body.update({"error": error} if error else {"result": {"content": "REDACTED"}})
    return {"@message": json.dumps({
        "eventTime": "t", "eventName": "InvokeGateway", "eventID": "e1",
        "resources": [{"ARN": gateway_arn}],
        "requestParameters": {"body": {"method": "tools/call", "params": {"name": "ops___purge",
                                                                         "arguments": "REDACTED"}}},
        "responseElements": {"statusCode": 200, "body": body},
        "additionalEventData": {"jwt": {"claims": {"sub": "client123", "client_id": "client123"}}},
    })}


def test_calls_name_tool_caller_and_error(monkeypatch):
    rows = [trail_event(error={"code": -32002, "message": "denied"}), trail_event("arn:other")]
    monkeypatch.setattr(records, "run_query", lambda *a: rows)
    trails = [{"name": "t", "logGroupArn": "arn:aws:logs:us-east-1:acct:log-group:/trail/g:*"}]
    c = records.callers(None, trails, GW_ARN, 0, 1)
    assert c["logGroup"] == "/trail/g"
    [call] = c["calls"]
    assert (call["tool"], call["sub"], call["error"]["code"]) == ("ops___purge", "client123", -32002)


def test_no_trail_is_a_gap():
    assert records.callers(None, [], GW_ARN, 0, 1)["status"] == "GAP"


class FakeTrail:
    def __init__(self, events):
        self.events = events

    def get_paginator(self, name):
        events = self.events

        class Pages:
            def paginate(self, **kw):
                return [{"Events": [{"CloudTrailEvent": json.dumps(e), "Resources": []} for e in events]}]
        return Pages()


def test_changes_leave_out_reads_and_token_requests():
    t = FakeTrail([
        {"eventName": "UpdateGateway", "readOnly": False},
        {"eventName": "GetGateway", "readOnly": True},
        {"eventName": "GetWorkloadAccessTokenForJWT", "readOnly": False},
    ])
    assert [c["eventName"] for c in records.changes(t, None, None)["changes"]] == ["UpdateGateway"]


def test_redaction_is_stable_and_keeps_digests():
    r = Redactor({"client": ["client123"]})
    out = r.value({
        "caller": "arn:aws:sts::acct:assumed-role/Admin/a.person",
        "sub": "client123",
        "allowed": ["client123"],
        "pool": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbC123/.well-known",
        "ip": "203.0.113.9",
        "sha256": "0123456789abcdef",
    })
    text = json.dumps(out)
    for value in ("a.person", "client123", "us-east-1_AbC123", "203.0.113.9"):
        assert value not in text
    assert out["sub"] == out["allowed"][0] == "<client-1>"
    assert out["sha256"] == "0123456789abcdef"


ACCOUNT = "111122223333"  # AWS documentation example account
PERSON = "someone@example.com"  # reserved example domain


def test_redaction_masks_accounts_and_people():
    out = Redactor().value({
        "role": f"arn:aws:iam::{ACCOUNT}:role/x",
        "account": ACCOUNT,
        "caller": f"arn:aws:sts::{ACCOUNT}:assumed-role/Admin/{PERSON}",
        "note": f"contact {PERSON}",
    })
    text = json.dumps(out)
    assert ACCOUNT not in text and PERSON not in text and "someone" not in text
    assert out["account"] == "<account-1>" and "<account-1>" in out["role"]


def test_redaction_turns_times_into_offsets():
    origin = datetime(2030, 1, 2, 3, 0, 0, tzinfo=UTC)
    later = (origin + timedelta(minutes=15, seconds=32)).isoformat()
    earlier = str(origin - timedelta(days=6, hours=2))
    out = Redactor(origin=origin).value({"a": later, "b": earlier, "c": f"at {later.replace('+00:00', 'Z')}"})
    assert out == {"a": "T+00:15:32", "b": "T-6d 02:00:00", "c": "at T+00:15:32"}


def test_client_ids_come_from_authorizers_and_calls():
    pack = {"identity": {"gateway": {"jwt": {"allowedClients": ["g1"]}},
                         "runtimes": [{"jwt": {"allowedClients": ["r1"]}}, {"jwt": None}]},
            "callers": {"calls": [{"sub": "g1", "clientId": "g1"}]}}
    assert set(client_ids(pack)) == {"g1", "r1"}


def test_control_takes_its_weakest_check():
    assert checks.worst(["PASS", "GAP"]) == "GAP"
    assert checks.worst(["GAP", "FAIL", "PASS"]) == "FAIL"


def minimal_pack():
    return {
        "inventory": {"gateway": {"name": "gw"}, "targets": [{"name": "t"}], "runtimes": []},
        "identity": {"gateway": {"authorizerType": "CUSTOM_JWT",
                                 "jwt": {"allowedClients": ["c"], "allowedAudience": []}}, "runtimes": []},
        "policies": [{"name": "forbid_x", "status": "ACTIVE", "enforcementMode": "ACTIVE",
                      "effects": ["forbid"], "statement": "forbid(principal, action, resource);"}],
        "enforcement": {"engineAttached": True, "engineArn": "arn:x/e1", "gatewayMode": "ENFORCE",
                        "policies": {"forbid_x": "ACTIVE"}, "policiesNotEnforced": [], "enforced": True},
        "decisions": {"counts": {}, "decisions": []},
        "callers": {"status": "GAP", "reason": "no trail", "calls": []},
        "changes": {"changes": []},
        "retention": {"logGroups": [], "trails": []},
    }


def test_pack_manifest_hashes_every_file(tmp_path):
    controls = [{"ask": "Stop", "checks": ["policies.forbid_present"],
                 "sources": [{"source": "s", "section": "1", "quote": "q", "url": "u"}]}]
    run = {"gateway": "gw", "region": "r", "start": "a", "end": "b", "collectedAt": "c", "caller": "x"}
    report.write_pack(tmp_path, minimal_pack(), controls, run)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "policies/forbid_x.cedar" in manifest["files"] and "summary.md" in manifest["files"]
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    assert "statement" not in (tmp_path / "policies.json").read_text()
    assert "| Stop | **PASS** |" in (tmp_path / "summary.md").read_text()


def test_bundled_controls_name_only_known_checks():
    controls = yaml.safe_load(resources.files("agentcore_evidence").joinpath("controls.yaml").read_text())
    used = {c for control in controls for c in control["checks"]}
    assert used <= set(checks.CHECKS)
    assert all(s["quote"] and s["url"].startswith("https://") for c in controls for s in c["sources"])


def test_refuses_a_directory_with_files(tmp_path):
    (tmp_path / "old.json").write_text("{}")
    with pytest.raises(SystemExit, match="not empty"):
        cli.main(["collect", "--gateway", "g", "--region", "us-east-1", "--out", str(tmp_path)])
