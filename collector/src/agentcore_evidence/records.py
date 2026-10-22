"""What the agents did, who called, what changed, and how the record is kept.

Decisions come from the Gateway's spans, calls from a CloudTrail trail that records
Gateway data events, and changes from CloudTrail management events. Tool arguments
and results are never collected: the spans do not carry them and CloudTrail redacts them.
"""
import json
from datetime import datetime

from botocore.exceptions import ClientError

from agentcore_evidence.insights import run_query

SPANS = "aws/spans"
SOURCE = "bedrock-agentcore.amazonaws.com"
GATEWAY_TYPE = "AWS::BedrockAgentCore::Gateway"
MAX_ROWS = 10000
DECISION = "aws.agentcore.policy.authorization_decision"
# Calls that change configuration. Token requests are also writes to CloudTrail, but
# they are credential use, not change.
CHANGE_VERBS = ("Create", "Update", "Delete", "Put", "Start", "Stop", "Synchronize", "Set", "Tag", "Untag")


def decisions(logs, gateway_id: str, start: int, end: int) -> dict:
    """Each policy decision on the Gateway, joined to the tool it was for.

    The policy span names the decision and the policy behind it but not the tool. The
    Gateway's tool span names the tool. Both carry the same request id.
    """
    query = (
        "fields @timestamp, @message"
        f' | filter attributes.aws.agentcore.policy.target_resource.id = "{gateway_id}"'
        f' or (name = "AgentCore.Gateway.InvokeTool" and attributes.gateway.id = "{gateway_id}")'
        f" | sort @timestamp desc | limit {MAX_ROWS}"
    )
    spans = [json.loads(r["@message"]) for r in run_query(logs, SPANS, query, start, end, MAX_ROWS)]
    tools = {}
    for s in spans:
        a = s.get("attributes", {})
        if s.get("name") == "AgentCore.Gateway.InvokeTool" and a.get("tool.name"):
            tools[a.get("aws.request.id")] = a["tool.name"]
    rows = []
    for s in spans:
        a = s.get("attributes", {})
        if s.get("name") == "AgentCore.Gateway.InvokeTool" or DECISION not in a:
            continue
        rows.append({
            "time": nanos_to_iso(s.get("endTimeUnixNano")),
            "requestId": a.get("aws.request.id"),
            "traceId": s.get("traceId"),
            "tool": tools.get(a.get("aws.request.id")),
            "decision": a[DECISION],
            "determiningPolicies": a.get("aws.agentcore.policy.determining_policies", []),
            "reason": a.get("aws.agentcore.policy.authorization_reason"),
            "mode": a.get("aws.agentcore.gateway.policy.mode"),
        })
    counts = {}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    return {"source": SPANS, "counts": counts, "decisions": rows}


def nanos_to_iso(nanos) -> str | None:
    return datetime.fromtimestamp(int(nanos) / 1e9).astimezone().isoformat() if nanos else None


def selects_gateway(selectors: dict, gateway_arn: str) -> bool:
    """Whether a trail's advanced selectors record data events for this Gateway."""
    for selector in selectors.get("AdvancedEventSelectors") or []:
        fields = {f["Field"]: f for f in selector["FieldSelectors"]}
        if fields.get("eventCategory", {}).get("Equals") != ["Data"]:
            continue
        if GATEWAY_TYPE not in fields.get("resources.type", {}).get("Equals", []):
            continue
        arn = fields.get("resources.ARN")
        if arn is None:
            return True
        if gateway_arn in arn.get("Equals", []) or any(
                gateway_arn.startswith(p) for p in arn.get("StartsWith", [])):
            return True
    return False


def gateway_trails(cloudtrail, gateway_arn: str, region: str) -> list[dict]:
    found = []
    for t in cloudtrail.describe_trails(includeShadowTrails=True)["trailList"]:
        if t.get("HomeRegion") != region and not t.get("IsMultiRegionTrail"):
            continue
        try:
            selectors = cloudtrail.get_event_selectors(TrailName=t["TrailARN"])
            status = cloudtrail.get_trail_status(Name=t["TrailARN"])
        except ClientError:
            continue  # A trail this caller cannot read, such as another account's.
        if selects_gateway(selectors, gateway_arn):
            found.append({
                "name": t["Name"],
                "arn": t["TrailARN"],
                "logging": status.get("IsLogging"),
                "logFileValidation": t.get("LogFileValidationEnabled"),
                "kmsKeyId": t.get("KmsKeyId"),
                "s3Bucket": t.get("S3BucketName"),
                "logGroupArn": t.get("CloudWatchLogsLogGroupArn"),
            })
    return found


def callers(logs, trails: list[dict], gateway_arn: str, start: int, end: int) -> dict:
    """Each call to the Gateway as CloudTrail recorded it, with the caller's token claims."""
    readable = [t for t in trails if t["logGroupArn"]]
    if not readable:
        why = ("no trail records data events for this Gateway" if not trails
               else "the trail delivers to S3 only. This version reads trails sent to CloudWatch Logs")
        return {"status": "GAP", "reason": why, "trails": trails, "calls": []}
    group = readable[0]["logGroupArn"].split(":log-group:", 1)[1].removesuffix(":*")
    query = ('fields @message | filter eventName = "InvokeGateway"'
             f" | sort @timestamp desc | limit {MAX_ROWS}")
    calls = []
    for row in run_query(logs, group, query, start, end, MAX_ROWS):
        e = json.loads(row["@message"])
        if gateway_arn not in {r.get("ARN") for r in e.get("resources", [])}:
            continue
        body = (e.get("requestParameters") or {}).get("body") or {}
        response = e.get("responseElements") or {}
        claims = ((e.get("additionalEventData") or {}).get("jwt") or {}).get("claims") or {}
        calls.append({
            "time": e.get("eventTime"),
            "eventId": e.get("eventID"),
            "method": body.get("method"),
            "tool": (body.get("params") or {}).get("name"),
            "sub": claims.get("sub"),
            "clientId": claims.get("client_id"),
            "scope": claims.get("scope"),
            "statusCode": response.get("statusCode"),
            "error": (response.get("body") or {}).get("error"),
            "sourceIp": e.get("sourceIPAddress"),
            "userAgent": e.get("userAgent"),
        })
    return {"status": "OK", "trail": readable[0]["name"], "logGroup": group, "calls": calls}


def changes(cloudtrail, start: datetime, end: datetime) -> dict:
    """Every AgentCore control-plane write in the window: who made it and what it was."""
    rows = []
    pages = cloudtrail.get_paginator("lookup_events").paginate(
        LookupAttributes=[{"AttributeKey": "EventSource", "AttributeValue": SOURCE}],
        StartTime=start, EndTime=end)
    for page in pages:
        for ev in page["Events"]:
            e = json.loads(ev["CloudTrailEvent"])
            if e.get("readOnly", True) or not e.get("eventName", "").startswith(CHANGE_VERBS):
                continue
            rows.append({
                "time": e.get("eventTime"),
                "eventName": e.get("eventName"),
                "actor": (e.get("userIdentity") or {}).get("arn"),
                "resources": [r.get("ResourceName") for r in ev.get("Resources", [])],
                "errorCode": e.get("errorCode"),
                "eventId": e.get("eventID"),
            })
    return {"source": "CloudTrail management events (LookupEvents)", "changes": rows}


def log_groups(logs, names: list[str], prefixes: list[str]) -> list[dict]:
    groups = {}
    for prefix in [*names, *prefixes]:
        for page in logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
            for g in page["logGroups"]:
                if prefix in names and g["logGroupName"] != prefix:
                    continue
                groups[g["logGroupName"]] = {
                    "name": g["logGroupName"],
                    "kmsKeyId": g.get("kmsKeyId"),
                    "retentionInDays": g.get("retentionInDays"),
                    "dataProtection": g.get("dataProtectionStatus"),
                }
    return sorted(groups.values(), key=lambda g: g["name"])


def retention(logs, trails: list[dict], runtime_ids: list[str]) -> dict:
    """How each record is kept: key, retention, masking, and file validation for trails."""
    trail_groups = [t["logGroupArn"].split(":log-group:", 1)[1].removesuffix(":*")
                    for t in trails if t["logGroupArn"]]
    prefixes = [f"/aws/bedrock-agentcore/runtimes/{rid}" for rid in runtime_ids]
    return {"logGroups": log_groups(logs, [SPANS, *trail_groups], prefixes), "trails": trails}
