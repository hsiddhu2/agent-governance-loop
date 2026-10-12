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


def list_tools(url: str, token: str) -> list[str]:
    names, cursor = [], None
    while True:
        params = {"cursor": cursor} if cursor else {}
        resp = requests.post(url, timeout=30, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params})
        resp.raise_for_status()
        result = resp.json()["result"]
        names += [t["name"] for t in result["tools"]]
        cursor = result.get("nextCursor")
        if not cursor:
            return names


def schema_tools() -> list[str]:
    return [t["name"] for f in sorted(Path("tools").glob("*/schema.json"))
            for t in json.loads(f.read_text())]


def main() -> None:
    outs = cfn_outputs(STACK)
    listed = list_tools(outs["GatewayUrl"], gateway_token(outs))
    print("tools/list returned:", json.dumps(listed, indent=2))

    mapping = {}
    for short in schema_tools():
        hits = [n for n in listed if n.endswith(short)]
        # Prefer the shortest hit so get_store never claims a longer name.
        if hits:
            mapping[short] = min(hits, key=len)

    missing = sorted(set(schema_tools()) - mapping.keys())
    if missing:
        sys.exit(f"Gateway did not list these schema tools: {missing}")

    OUT.write_text(json.dumps(mapping, indent=2) + "\n")
    print(f"wrote {OUT}:", json.dumps(mapping, indent=2))


if __name__ == "__main__":
    main()
