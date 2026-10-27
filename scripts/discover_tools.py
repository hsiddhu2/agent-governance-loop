"""Ask the deployed Gateway for its tool names and save them for policy rendering.

Writes policies/tool_names.json (each schema tool's name as the Gateway lists it) and
policies/gateway.json (the Gateway's ARN and each agent's client id, its Cedar
principal). scripts/render_policy.py fills the templates from both.

The Gateway prefixes each tool with its target name. The exact prefix format is
not assumed here: each listed name is matched to a schema tool by suffix.

Also the shared helpers the other scripts import: stack outputs, an agent's Gateway
token, one MCP call, and the Gateway's live policy mode.
"""
import json
import sys
from pathlib import Path

import boto3
import requests

REGION = "us-east-1"
STACK = "AglGateway"
OUT = Path("policies/tool_names.json")
GATEWAY_OUT = Path("policies/gateway.json")


def cfn_outputs(stack: str) -> dict:
    cf = boto3.client("cloudformation", region_name=REGION)
    outs = cf.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
    return {o["OutputKey"]: o["OutputValue"] for o in outs}


# Which stack outputs hold each agent's Gateway client and the scopes it may ask for.
AGENT_CLIENTS = {
    "ops": ("OpsAgentClientId", "Scopes"),
    "support": ("SupportAgentClientId", "SupportScopes"),
}


def gateway_token(outs: dict, agent: str = "ops") -> str:
    # Operator tooling, run with the operator's own AWS credentials. It reads an agent's
    # client secret on purpose: the scenarios call the Gateway with the agent's
    # credential, without the model, to show what policy decides. The agents never call
    # Cognito for them. Each agent gets its Gateway token from AgentCore Identity.
    client_key, scopes_key = AGENT_CLIENTS[agent]
    secret = boto3.client("cognito-idp", region_name=REGION).describe_user_pool_client(
        UserPoolId=outs["UserPoolId"], ClientId=outs[client_key],
    )["UserPoolClient"]["ClientSecret"]
    resp = requests.post(outs["TokenEndpoint"], timeout=10, data={
        "grant_type": "client_credentials",
        "client_id": outs[client_key],
        "client_secret": secret,
        "scope": outs[scopes_key].replace(",", " "),
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


def kept_from_last_run(missing: list[str], found: dict[str, str], previous: dict[str, str],
                       mode: str | None) -> dict[str, str] | None:
    """Names for tools hidden by policy, taken from the last discovery, or None.

    Under ENFORCE, tools/list leaves out tools that no policy allows, such as one
    under an explicit forbid. Their names are reused from the last live discovery
    only when every tool still listed has exactly the name recorded then, so the
    target prefix is unchanged. A tool never discovered before is not guessed.
    """
    if mode != "ENFORCE" or not found:
        return None
    if any(previous.get(short) != name for short, name in found.items()):
        return None
    if any(short not in previous for short in missing):
        return None
    return {short: previous[short] for short in missing}


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
        mode = gateway_mode()
        previous = json.loads(OUT.read_text()) if OUT.exists() else {}
        kept = kept_from_last_run(missing, mapping, previous, mode)
        if kept is None:
            sys.exit(missing_tools_message(missing, mode))
        print("kept from the last discovery, hidden by policy under ENFORCE:", json.dumps(kept, indent=2))
        mapping = {short: {**mapping, **kept}[short] for short in schema_tools()}

    OUT.write_text(json.dumps(mapping, indent=2) + "\n")
    print(f"wrote {OUT}:", json.dumps(mapping, indent=2))
    # Policies name the Gateway they apply to, since AgentCore rejects an unconstrained
    # resource, and the agent each permit is for. The Gateway's Cedar principal for a
    # Cognito M2M token is the token's client id.
    GATEWAY_OUT.write_text(json.dumps({
        "arn": outs["GatewayArn"],
        "principals": {"ops_agent": outs["OpsAgentClientId"],
                       "support_agent": outs["SupportAgentClientId"]},
    }, indent=2) + "\n")
    print(f"wrote {GATEWAY_OUT}")


if __name__ == "__main__":
    main()
