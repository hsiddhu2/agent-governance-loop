"""Find a tool in the catalog, then call it as the support agent, without the model.

Discovery and permission are separate. The catalog lists every tool the Gateway
offers, the purge included, and anyone allowed to search it can find that tool.
Finding it grants nothing: the call still goes through the Gateway, where policy
decides. This searches the catalog for a destructive tool, takes the Gateway and the
tool from the record it returns, and calls the tool with the support agent's own
credential. Runs only while the Gateway enforces.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import boto3

from access_matrix import outcome
from discover_tools import STACK, cfn_outputs, gateway_mode, gateway_token, mcp_call

REGION = "us-east-1"
TOOL_NAMES = Path("policies/cedar/tool_names.json")
SEARCH_SECONDS = 120


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--query", default="permanently delete claim records")
    p.add_argument("--agent", default="support")
    a = p.parse_args()
    if gateway_mode() != "ENFORCE":
        sys.exit("The Gateway is not enforcing, so the call would really run. Run `make enforce` first.")

    registry = cfn_outputs("AglRegistry")["RegistryArn"]
    search = boto3.client("agent-registry", region_name=REGION)
    # An approved record reaches search after a short indexing delay, so search again
    # for a while before giving up.
    give_up_at = time.time() + SEARCH_SECONDS
    while True:
        found = search.search_discoverable_registry_records(
            registryIds=[registry], searchQuery=a.query, maxResults=5)["registryRecords"]
        servers = [r for r in found if r["recordType"] == "MCP"]
        if servers or time.time() > give_up_at:
            break
        time.sleep(5)
    print(f"search {a.query!r}: {[r['name'] for r in found]}")
    if not servers:
        sys.exit("no approved MCP record matched. Has `make approve-catalog` run?")

    record = servers[0]
    url = json.loads(record["descriptors"]["mcpServer"]["data"])["remotes"][0]["url"]
    tools = json.loads(record["descriptors"]["mcpServer"]["additionalData"]["tools"]["data"])["tools"]
    # The record lists tools as their targets declare them. The Gateway's own names,
    # which carry the target, come from discovery.
    destructive = next(t for t in tools if "delete" in t["description"].lower())
    gateway_name = json.loads(TOOL_NAMES.read_text())[destructive["name"]]
    print(f"record {record['name']} ({record['status']}): Gateway {url}")
    print(f"tool found: {destructive['name']}: {destructive['description']}")

    outs = cfn_outputs(STACK)
    if url != outs["GatewayUrl"]:
        sys.exit("the record's Gateway is not the deployed one")
    status, body = mcp_call(url, gateway_token(outs, a.agent), "tools/call",
                            {"name": gateway_name, "arguments": {"environment": "staging"}})
    result = outcome(status, body)
    print(f"{a.agent} agent calls {destructive['name']}: {result}")
    # Finding the tool must not have let the call run.
    sys.exit(0 if result.startswith("denied") else 1)


if __name__ == "__main__":
    main()
