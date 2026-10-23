import json
import os

import boto3

ddb = boto3.client("dynamodb")
PREFIX = os.environ["TABLE_PREFIX"]
TOOLS = ("get_ticket",)


def _tool_name(context) -> str:
    # The Gateway passes the full, target-prefixed tool name. Match on the known
    # tool names rather than splitting on a separator, which is not stable.
    full = context.client_context.custom["bedrockAgentCoreToolName"]
    matches = [t for t in TOOLS if full.endswith(t)]
    if not matches:
        raise ValueError(f"unknown tool {full}")
    return max(matches, key=len)


def get_ticket(env: str, ticket_id: str) -> dict:
    """One support ticket as the customer wrote it.

    The subject and body are customer input: they can carry identifiers the customer
    pasted and text written to instruct whoever reads it. The tool returns them as
    stored. The Gateway's policies decide what the agent may do and what it may read.
    """
    item = ddb.get_item(TableName=f"{PREFIX}{env}", Key={"pk": {"S": ticket_id}}).get("Item")
    if item is None:
        raise ValueError(f"no ticket {ticket_id} in {env}")
    return {
        "ticket_id": ticket_id,
        "claim_id": item["claim_id"]["S"],
        "status": item["status"]["S"],
        "subject": item["subject"]["S"],
        "body": item["body"]["S"],
    }


def handler(event, context):
    tool = _tool_name(context)
    # Which tool ran and for which request. Arguments and results are not logged:
    # tickets hold whatever a customer typed.
    print(json.dumps({"tool": tool, "request_id": context.aws_request_id}))

    if tool == "get_ticket":
        return get_ticket(event["environment"], event["ticket_id"])
    raise ValueError(f"unhandled tool {tool}")
