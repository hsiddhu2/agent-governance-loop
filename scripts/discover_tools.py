"""Ask the deployed Gateway for its tool names and save them for policy rendering.

The Gateway prefixes each tool with its target name. The exact prefix format is
not assumed here: each listed name is matched to a schema tool by suffix.
"""
import json
import sys
from pathlib import Path

import boto3
import requests

REGION = "us-east-1"
STACK = "AglGateway"
OUT = Path("policies/cedar/tool_names.json")
GATEWAY_OUT = Path("policies/cedar/gateway.json")


def cfn_outputs(stack: str) -> dict:
    cf = boto3.client("cloudformation", region_name=REGION)
    outs = cf.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in outs}


def gateway_token(outs: dict) -> str:
    secret = boto3.client("cognito-idp", region_name=REGION).describe_user_pool_client(
        UserPoolId=outs["UserPoolId"], ClientId=outs["ClientId"],
    )["UserPoolClient"]["ClientSecret"]
    resp = requests.post(outs["TokenEndpoint"], timeout=10, data={
        "grant_type": "client_credentials",
        "client_id": outs["ClientId"],
        "client_secret": secret,
        "scope": outs["Scopes"].replace(",", " "),
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def mcp_call(url: str, token: str, method: str, params: dict) -> tuple[int, object]:
    """Send one JSON-RPC request to the Gateway. Returns the HTTP status and the parsed body.

    The Gateway may answer with plain JSON or with a server-sent event stream; both are handled.
    Non-200 replies are returned, not raised, so callers can show a refusal as it came back.
    """
    resp = requests.post(url, timeout=30, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if resp.headers.get("Content-Type", "").startswith("text/event-stream"):
        events = [line[5:].strip() for line in resp.text.splitlines() if line.startswith("data:")]
        return resp.status_code, json.loads(events[-1]) if events else resp.text
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def list_tools(url: str, token: str) -> list[str]:
    names, cursor = [], None
    while True:
        status, body = mcp_call(url, token, "tools/list", {"cursor": cursor} if cursor else {})
        if status != 200 or not isinstance(body, dict) or "result" not in body:
            sys.exit(f"tools/list failed ({status}): {body}")
        names += [t["name"] for t in body["result"]["tools"]]
        cursor = body["result"].get("nextCursor")
        if not cursor:
            return names


def schema_tools() -> list[str]:
    return [t["name"] for f in sorted(Path("tools").glob("*/schema.json"))
            for t in json.loads(f.read_text())]


def missing_tools_message(missing: list[str], mode: str | None) -> str:
    """Explain why schema tools are absent from tools/list, given the Gateway's policy mode."""
    if mode == "ENFORCE":
        return (f"Gateway did not list these schema tools: {missing}. "
                "The Gateway is in ENFORCE, and tools/list hides tools that no policy allows yet. "
                "Run `make log-only`, then `make deploy`.")
    return f"Gateway did not list these schema tools: {missing}"


def gateway_mode() -> str | None:
    # Imported here because policy_mode imports this module.
    from policy_mode import find_gateway
    gw = find_gateway()
    return (gw or {}).get("policyEngineConfiguration", {}).get("mode")


def main() -> None:
    outs = cfn_outputs(STACK)
    listed = list_tools(outs["GatewayUrl"], gateway_token(outs))
    print("tools/list returned:", json.dumps(listed, indent=2))

    mapping = {}
    for short in schema_tools():
        hits = [n for n in listed if n.endswith(short)]
        # Prefer the shortest hit so get_claims_store never claims a longer name.
        if hits:
            mapping[short] = min(hits, key=len)

    missing = sorted(set(schema_tools()) - mapping.keys())
    if missing:
        sys.exit(missing_tools_message(missing, gateway_mode()))

    OUT.write_text(json.dumps(mapping, indent=2) + "\n")
    print(f"wrote {OUT}:", json.dumps(mapping, indent=2))
    # Policies name the Gateway they apply to. AgentCore rejects an unconstrained resource.
    GATEWAY_OUT.write_text(json.dumps({"arn": outs["GatewayArn"]}, indent=2) + "\n")
    print(f"wrote {GATEWAY_OUT}")


if __name__ == "__main__":
    main()
