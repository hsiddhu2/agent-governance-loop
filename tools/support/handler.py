import json
import os

import boto3
from botocore.exceptions import ClientError

ddb = boto3.client("dynamodb")
PREFIX = os.environ["TABLE_PREFIX"]
TOOLS = ("get_ticket",)


# The output fields each screened tool's screens read (policies/cedar/support_screen_*).
SCREENED = {"get_ticket": ("ticket_id", "claim_id", "status", "subject", "body")}


class NotFound(LookupError):
    """What the caller asked for does not exist. Its message is returned to the caller."""


def tool_error(message: str) -> dict:
    # The Gateway passes a result in this shape through as an MCP tool error with this
    # text. An exception reaches the caller only as "An internal error occurred. Please
    # retry later.", which reads as an outage. Measured, not documented.
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def not_found(tool: str, event: dict, message: str) -> dict:
    """A not-found the caller can read, in the shape its screens can check.

    A screen reads named output fields and withholds any result that lacks them, an
    error result included, and the detector can refuse empty fields. So a screened tool
    answers in its declared shape, every field filled, status not_found and the message
    in error.
    """
    fields = SCREENED.get(tool)
    if not fields:
        return tool_error(message)
    return {**dict.fromkeys(fields, "Not found."), "ticket_id": event.get("ticket_id", ""),
            "status": "not_found", "error": message}


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
        raise NotFound(f"No ticket {ticket_id} in {env}. Ticket ids look like ticket#7.")
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
    try:
        if tool == "get_ticket":
            return get_ticket(event["environment"], event["ticket_id"])
    except NotFound as e:
        return not_found(tool, event, str(e))
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        return tool_error(f"No ticket store for environment {event.get('environment')}.")
    raise ValueError(f"unhandled tool {tool}")
