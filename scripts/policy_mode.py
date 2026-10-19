"""Read the Gateway's live policy mode, and check it is safe to switch to ENFORCE.

`current` prints the mode the deployed Gateway runs in, so a redeploy keeps it
instead of resetting it. With no Gateway yet it prints LOG_ONLY. Any other error
stops the command rather than guessing a mode.

`check` runs before enforcement is switched on:
  1. every rendered .cedar file exists in the engine as an ACTIVE policy, and
  2. a fresh tools/list, evaluated in LOG_ONLY, shows at least one allowed tool.
With default deny, an engine that allows nothing would hide every tool the moment
it enforces. The second check reads that from the policy span, not from config.
"""
import json
import sys
import time
from pathlib import Path

import boto3

from discover_tools import cfn_outputs, gateway_token, mcp_call
from spans import query_spans

REGION = "us-east-1"
GATEWAY_NAME = "agl-gateway"
CEDAR_DIR = Path("policies/cedar")
SPAN_WAIT_SECONDS = 300

control = boto3.client("bedrock-agentcore-control", region_name=REGION)


def find_gateway() -> dict | None:
    for page in control.get_paginator("list_gateways").paginate():
        for gw in page["items"]:
            if gw["name"] == GATEWAY_NAME:
                return control.get_gateway(gatewayIdentifier=gw["gatewayId"])
    return None


def current() -> None:
    gw = find_gateway()
    if gw is None:
        print("LOG_ONLY")
        return
    config = gw.get("policyEngineConfiguration")
    if not config:
        sys.exit(f"{GATEWAY_NAME} has no policy engine attached")
    print(config["mode"])


def check_policies(engine_id: str) -> None:
    expected = {p.stem for p in CEDAR_DIR.glob("*.cedar")}
    if not expected:
        sys.exit("No rendered .cedar files. Run `make discover` first.")
    live = {}
    for page in control.get_paginator("list_policies").paginate(policyEngineId=engine_id):
        for p in page["policies"]:
            live[p["name"]] = p["status"]
    print("engine policies:", json.dumps(live, indent=2))
    missing = sorted(expected - live.keys())
    inactive = sorted(n for n in expected & live.keys() if live[n] != "ACTIVE")
    if missing or inactive:
        sys.exit(f"NOT READY: missing {missing}, not ACTIVE {inactive}")


def latest_listing_span(gateway_id: str, since: int) -> dict | None:
    """Return the newest tools/list policy decision for this Gateway since `since`."""
    found = query_spans(
        '| filter name = "AgentCore.Policy.PartiallyAuthorizeActions"\n'
        f'| filter attributes.aws.agentcore.policy.target_resource.id = "{gateway_id}"',
        start=since, end=int(time.time()) + 60, limit=1)
    if not found:
        return None
    attrs = found[0].get("attributes", {})
    return {
        "time": found[0]["@timestamp"],
        "mode": attrs.get("aws.agentcore.gateway.policy.mode"),
        "allowed": attrs.get("aws.agentcore.policy.allowed_tools", []),
        "denied": attrs.get("aws.agentcore.policy.denied_tools", []),
    }


def check() -> None:
    gw = find_gateway()
    if gw is None:
        sys.exit(f"{GATEWAY_NAME} is not deployed")
    engine_id = gw["policyEngineConfiguration"]["arn"].rsplit("/", 1)[-1]
    check_policies(engine_id)

    outs = cfn_outputs("AglGateway")
    since = int(time.time()) - 5
    status, body = mcp_call(outs["GatewayUrl"], gateway_token(outs), "tools/list", {})
    if status != 200:
        sys.exit(f"tools/list failed ({status}): {body}")

    # Spans reach aws/spans a little after the call. Wait for one, within limits.
    give_up_at = time.time() + SPAN_WAIT_SECONDS
    span = None
    while time.time() < give_up_at and span is None:
        span = latest_listing_span(gw["gatewayId"], since)
        if span is None:
            time.sleep(15)
    if span is None:
        sys.exit(f"NOT READY: no policy span for that tools/list within {SPAN_WAIT_SECONDS}s")

    print("policy span:", json.dumps(span, indent=2))
    allowed = span["allowed"]
    if not allowed:
        sys.exit("NOT READY: the engine allows no tools. ENFORCE would hide every tool.")
    print(f"READY: {len(allowed)} tool(s) allowed under the current policies")


if __name__ == "__main__":
    commands = {"current": current, "check": check}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: policy_mode.py {{{'|'.join(commands)}}}")
    commands[sys.argv[1]]()
