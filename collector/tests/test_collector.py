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


SCREEN = (
    "suppressOutput(\n  principal,\n  action == AgentCore::Action::\"ops___get_claim_record\",\n"
    f"  resource == AgentCore::Gateway::\"{GW_ARN}\"\n)\nwhen guardrails {{\n"
    "  BedrockGuardrails::SensitiveInformation([\"US_SOCIAL_SECURITY_NUMBER\"], "
    "[context.output.policyholder]).categories().contains(\"US_SOCIAL_SECURITY_NUMBER\")\n};"
)


class FakeEngine:
    def __init__(self, definitions):
        self.definitions = definitions

    def get_paginator(self, name):
        ids = list(self.definitions)

        class Pages:
            def paginate(self, **kw):
                return [{"policies": [{"policyId": i} for i in ids]}]
        return Pages()

    def get_policy(self, policyEngineId, policyId):
        return {"policyId": policyId, "name": policyId, "status": "ACTIVE", "enforcementMode": "ACTIVE",
                "definition": self.definitions[policyId]}


def test_guardrail_policy_statement_and_effect_are_read():
    engine = FakeEngine({"screen": {"policy": {"statement": SCREEN}},
                         "forbid": {"cedar": {"statement": "forbid(principal, action, resource);"}}})
    screen, forbid = control_plane.policies(engine, "e1")
    assert screen["statement"] == SCREEN and screen["effects"] == ["suppressOutput"]
    assert forbid["effects"] == ["forbid"]


ENFORCING = {"policyEngineConfiguration": {"arn": "arn:x:policy-engine/e1", "mode": "ENFORCE"}}


def test_log_only_permit_or_forbid_means_not_enforced():
    e = control_plane.enforcement(ENFORCING, [
        {"name": "a", "enforcementMode": "ACTIVE", "effects": ["permit"]},
        {"name": "b", "enforcementMode": "LOG_ONLY", "effects": ["forbid"]}])
    assert not e["enforced"] and e["policiesNotEnforced"] == ["b"]


def test_log_only_screen_does_not_weaken_enforcement():
    e = control_plane.enforcement(ENFORCING, [
        {"name": "permit", "enforcementMode": "ACTIVE", "effects": ["permit"]},
        {"name": "forbid", "enforcementMode": "ACTIVE", "effects": ["forbid"]},
        {"name": "screen_a", "enforcementMode": "ACTIVE", "effects": ["suppressOutput"]},
        {"name": "screen_b", "enforcementMode": "LOG_ONLY", "effects": ["suppressOutput"]}])
    assert e["enforced"] and e["policiesNotEnforced"] == []
    assert e["screens"] == {"screen_a": "ACTIVE", "screen_b": "LOG_ONLY"}
    status, finding = checks.enforced({"enforcement": e})
    assert status == "PASS" and "screen_b" in finding


def test_log_only_forbid_is_not_a_forbid_in_force():
    policies = [{"name": "forbid_x", "status": "ACTIVE", "enforcementMode": "LOG_ONLY",
                 "effects": ["forbid"]}]
    status, finding = checks.forbid_present({"policies": policies})
    assert status == "FAIL" and "forbid_x" in finding


def test_log_only_engine_means_not_enforced():
    gw = {"policyEngineConfiguration": {"arn": "arn:x:policy-engine/e1", "mode": "LOG_ONLY"}}
    assert not control_plane.enforcement(gw, [{"name": "a", "enforcementMode": "ACTIVE",
                                               "effects": ["forbid"]}])["enforced"]


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


def trail_event(gateway_arn=GW_ARN, error=None, status=200, request_id="r1"):
    body = {"jsonrpc": "2.0", "id": 1}
    body.update({"error": error} if error else {"result": {"content": "REDACTED"}})
    return {"@message": json.dumps({
        "eventTime": "t", "eventName": "InvokeGateway", "eventID": "e1", "requestID": request_id,
        "resources": [{"ARN": gateway_arn}],
        "requestParameters": {"body": {"method": "tools/call", "params": {"name": "ops___purge",
                                                                         "arguments": "REDACTED"}}},
        "responseElements": {"statusCode": status, "body": body},
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


PERMIT = "ops_permit_read_tools-1"
SCREEN_ID = "ops_screen_government_ids-1"
TRAIL = [{"name": "t", "logGroupArn": "arn:aws:logs:us-east-1:acct:log-group:/trail/g:*"}]


def authorize(request_id):
    return span("AgentCore.Policy.AuthorizeAction", **{
        "aws.request.id": request_id, records.DECISION: "ALLOW",
        "aws.agentcore.policy.determining_policies": [PERMIT],
        "aws.agentcore.gateway.policy.mode": "ENFORCE"})


def invoke(request_id, status):
    return span("AgentCore.Gateway.InvokeTool", **{
        "aws.request.id": request_id, "tool.name": "ops___get_claim_record", records.DECISION: "ALLOW",
        "http.response.status_code": status})


def test_call_authorized_for_request_and_response_is_one_decision(monkeypatch):
    rows = [authorize("r1"), authorize("r1"), invoke("r1", 200)]
    monkeypatch.setattr(records, "run_query", lambda *a: rows)
    d = records.decisions(None, "gw-abc", 0, 1)
    assert d["counts"] == {"ALLOW": 1}
    [row] = d["decisions"]
    assert row["determiningPolicies"] == [PERMIT] and row["authorizations"] == 2


def test_suppression_comes_from_cloudtrail_not_spans(monkeypatch):
    monkeypatch.setattr(records, "run_query", lambda *a: [authorize("r2"), invoke("r2", 403)])
    d = records.decisions(None, "gw-abc", 0, 1)
    assert d["counts"] == {"ALLOW": 1} and d["decisions"][0]["suppressedBy"] is None

    blocked = {"code": -32002,
               "message": f"Output blocked by policy: Policy evaluation denied due to {SCREEN_ID}"}
    event = trail_event(error=blocked, status=403, request_id="r2")
    monkeypatch.setattr(records, "run_query", lambda *a: [event])
    c = records.callers(None, TRAIL, GW_ARN, 0, 1)
    assert c["calls"][0]["suppressedBy"] == [SCREEN_ID]

    d = records.join_suppressions(d, c)
    assert d["counts"] == {"SUPPRESSED": 1}
    [row] = d["decisions"]
    assert row["decision"] == "ALLOW" and row["suppressedBy"] == [SCREEN_ID]
    status, finding = checks.suppression_names_policy({"callers": c})
    assert status == "PASS" and SCREEN_ID in finding


def test_a_withhold_by_two_screens_names_both():
    # Recorded live: one response withheld by two screens names both, comma-separated.
    message = ("Output blocked by policy: Policy evaluation denied due to "
               "support_screen_government_ids-abc, support_screen_financial-def")
    assert records.suppressed_by(403, {"code": -32002, "message": message}) == [
        "support_screen_government_ids-abc", "support_screen_financial-def"]


def test_a_denied_call_is_not_a_suppression(monkeypatch):
    denied = {"code": -32002, "message": "Tool call denied by policy"}
    monkeypatch.setattr(records, "run_query", lambda *a: [trail_event(error=denied, status=403)])
    c = records.callers(None, TRAIL, GW_ARN, 0, 1)
    assert c["calls"][0]["suppressedBy"] is None
    assert checks.suppression_names_policy({"callers": c})[0] == "GAP"


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


def test_each_change_names_what_it_changed():
    # requestParameters as LookupEvents returns them. Resources is empty for policy events.
    t = FakeTrail([
        {"eventName": "CreatePolicy", "readOnly": False, "requestParameters": {
            "name": "ops_permit_read_tools", "policyEngineId": "e1", "clientToken": "x"}},
        {"eventName": "DeletePolicy", "readOnly": False, "requestParameters": {
            "policyId": "ops_permit_reads-1", "policyEngineId": "e1"}},
        {"eventName": "UpdatePolicy", "readOnly": False, "requestParameters": {
            "policyId": "ops_screen_x-1", "policyEngineId": "e1", "enforcementMode": "ACTIVE"}},
        {"eventName": "CreatePolicyEngine", "readOnly": False, "requestParameters": {"name": "engine"}},
        {"eventName": "DeletePolicyEngine", "readOnly": False, "requestParameters": {"policyEngineId": "e2"}},
        {"eventName": "UpdateGateway", "readOnly": False, "requestParameters": {
            "gatewayIdentifier": "gw-abc", "name": "gw"}},
        {"eventName": "TagResource", "readOnly": False, "requestParameters": {"resourceArn": "arn:x"}},
    ])
    targets = [(c["eventName"], c["target"]) for c in records.changes(t, None, None)["changes"]]
    assert targets == [("CreatePolicy", "ops_permit_read_tools"), ("DeletePolicy", "ops_permit_reads-1"),
                       ("UpdatePolicy", "ops_screen_x-1"), ("CreatePolicyEngine", "engine"),
                       ("DeletePolicyEngine", "e2"), ("UpdateGateway", "gw-abc"), ("TagResource", None)]


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


def test_policy_digest_matches_the_redacted_statement_in_the_pack(tmp_path):
    pack = minimal_pack()
    pack["policies"][0]["statement"] = \
        f'forbid(principal, action, resource == AgentCore::Gateway::"{GW_ARN.replace("acct", ACCOUNT)}");'
    run = {"gateway": "gw", "region": "r", "start": "a", "end": "b", "collectedAt": "c", "caller": "x"}
    report.write_pack(tmp_path, Redactor().value(pack), [], run)
    written = (tmp_path / "policies" / "forbid_x.cedar").read_bytes()
    assert ACCOUNT not in written.decode()
    [entry] = json.loads((tmp_path / "policies.json").read_text())
    assert entry["sha256"] == hashlib.sha256(written).hexdigest()


def pack_with_late_trail(decision_times, call_times):
    pack = minimal_pack()
    pack["decisions"] = {"counts": {"ALLOW": len(decision_times)}, "decisions": [
        {"time": t, "requestId": f"r{i}", "decision": "ALLOW", "determiningPolicies": [],
         "suppressedBy": None} for i, t in enumerate(decision_times)]}
    pack["callers"] = {"status": "OK", "trail": "t", "calls": [
        {"time": t, "requestId": "r0", "sub": "c", "suppressedBy": None} for t in call_times]}
    return pack


def test_summary_explains_decisions_without_calls(tmp_path):
    origin = datetime(2030, 1, 2, tzinfo=UTC)
    pack = pack_with_late_trail(["2030-01-02T01:00:00+00:00", "2030-01-02T05:00:00+00:00"],
                                ["2030-01-02T04:00:00Z"])
    run = {"gateway": "gw", "region": "r", "start": "a", "end": "b", "collectedAt": "c", "caller": "x"}
    report.write_pack(tmp_path, Redactor(origin=origin).value(pack), [], run)
    text = (tmp_path / "summary.md").read_text()
    assert "2 decisions but 1 recorded call" in text
    assert "first recorded event, T+04:00:00, is later than the earliest decision, T+01:00:00" in text


def test_summary_adds_no_note_when_every_decision_has_a_call(tmp_path):
    pack = pack_with_late_trail(["2030-01-02T01:00:00+00:00"], ["2030-01-02T01:00:00Z"])
    run = {"gateway": "gw", "region": "r", "start": "a", "end": "b", "collectedAt": "c", "caller": "x"}
    report.write_pack(tmp_path, pack, [], run)
    assert "recorded call" not in (tmp_path / "summary.md").read_text()


def test_bundled_controls_name_only_known_checks():
    controls = yaml.safe_load(resources.files("agentcore_evidence").joinpath("controls.yaml").read_text())
    used = {c for control in controls for c in control["checks"]}
    assert used <= set(checks.CHECKS)
    assert all(s["quote"] and s["url"].startswith("https://") for c in controls for s in c["sources"])


def test_refuses_a_directory_with_files(tmp_path):
    (tmp_path / "old.json").write_text("{}")
    with pytest.raises(SystemExit, match="not empty"):
        cli.main(["collect", "--gateway", "g", "--region", "us-east-1", "--out", str(tmp_path)])
