"""Review the catalog's draft records against what is deployed, then approve or reject each.

Publishing and approving are separate steps. The registry stack publishes records as
drafts, and nothing is returned by search until it is approved. This is the reviewer:
a record is approved only when what it says matches the live account, and rejected,
with the reason, when it does not. A team would run this step under a role that can
change a record's status and cannot publish one.
"""
import json
import sys

import boto3

from discover_tools import STACK as GATEWAY_STACK
from discover_tools import cfn_outputs

REGION = "us-east-1"
REGISTRY_STACK = "AglRegistry"


def check_gateway(record: dict, gateway: dict) -> list[str]:
    server = json.loads(record["descriptors"]["mcpServer"]["data"])
    urls = [r["url"] for r in server.get("remotes", [])]
    problems = [] if gateway["gatewayUrl"] in urls else [f"remote {urls} is not the live Gateway URL"]
    if gateway["status"] != "READY":
        problems.append(f"Gateway is {gateway['status']}")
    return problems


def check_agent(record: dict, gateway: dict, control) -> list[str]:
    agent = json.loads(record["descriptors"]["custom"]["data"])
    problems = []
    runtime_id = agent["runtime"]["arn"].rsplit("/", 1)[-1]
    try:
        status = control.get_agent_runtime(agentRuntimeId=runtime_id)["status"]
        if status != "READY":
            problems.append(f"runtime {runtime_id} is {status}")
    except control.exceptions.ResourceNotFoundException:
        problems.append(f"runtime {runtime_id} does not exist")
    if agent["gateway"]["url"] != gateway["gatewayUrl"]:
        problems.append("Gateway URL is not the live one")
    allowed = gateway["authorizerConfiguration"]["customJWTAuthorizer"].get("allowedClients", [])
    if agent["gateway"]["principal"] not in allowed:
        problems.append("its Gateway principal is not a client the Gateway accepts")
    return problems


def main() -> None:
    registry = cfn_outputs(REGISTRY_STACK)["RegistryId"]
    gateway_arn = cfn_outputs(GATEWAY_STACK)["GatewayArn"]
    reg = boto3.client("agent-registry-control", region_name=REGION)
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    gateway = control.get_gateway(gatewayIdentifier=gateway_arn.rsplit("/", 1)[-1])

    rejected = 0
    for page in reg.get_paginator("list_registry_records").paginate(registryId=registry):
        for summary in page["registryRecords"]:
            name, record_id, status = summary["name"], summary["recordId"], summary["status"]
            if status not in ("DRAFT", "PENDING_APPROVAL"):
                print(f"{name}: {status}, nothing to review")
                continue
            record = reg.get_registry_record(registryId=registry, recordId=record_id)
            if record["recordType"] == "MCP":
                problems = check_gateway(record, gateway)
            elif json.loads(record["descriptors"]["custom"]["data"]).get("kind") == "agent":
                problems = check_agent(record, gateway, control)
            else:
                problems = ["not a record this pattern publishes"]
            if status == "DRAFT":
                reg.submit_registry_record_for_approval(registryId=registry, recordId=record_id)
            if problems:
                rejected += 1
                reason = "; ".join(problems)
                reg.update_registry_record_status(registryId=registry, recordId=record_id,
                                                  status="REJECTED", statusReason=reason[:1000])
                print(f"{name}: REJECTED, {reason}")
            else:
                reg.update_registry_record_status(registryId=registry, recordId=record_id, status="APPROVED",
                                                  statusReason="Matches the deployed resources it describes")
                print(f"{name}: APPROVED")
    sys.exit(1 if rejected else 0)


if __name__ == "__main__":
    main()
