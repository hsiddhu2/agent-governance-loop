import json
import os
import time

import boto3

ddb = boto3.client("dynamodb")
PREFIX = os.environ["TABLE_PREFIX"]
MAX_ATTEMPTS = 6
TOOLS = ("list_env", "get_claims_store", "purge_claims")


def _tool_name(context) -> str:
    # The Gateway passes the full, target-prefixed tool name. Match on the known
    # tool names rather than splitting on a separator, which is not stable.
    full = context.client_context.custom["bedrockAgentCoreToolName"]
    matches = [t for t in TOOLS if full.endswith(t)]
    if not matches:
        raise ValueError(f"unknown tool {full}")
    return max(matches, key=len)


# Stop starting new pages with this much time left, so the function returns a count
# instead of timing out mid-purge.
RESERVE_MS = 5000


def _purge(table: str, context) -> tuple[int, bool]:
    """Delete every record in `table`. Returns how many were deleted and whether it finished."""
    deleted = 0
    for page in ddb.get_paginator("scan").paginate(TableName=table, ProjectionExpression="pk"):
        if context.get_remaining_time_in_millis() < RESERVE_MS:
            return deleted, False
        keys = [{"pk": item["pk"]} for item in page["Items"]]
        # BatchWriteItem takes up to 25 requests. Unprocessed ones are retried with
        # exponential backoff, as the DynamoDB docs advise.
        for i in range(0, len(keys), 25):
            requests = [{"DeleteRequest": {"Key": k}} for k in keys[i:i + 25]]
            for attempt in range(MAX_ATTEMPTS):
                resp = ddb.batch_write_item(RequestItems={table: requests})
                requests = resp.get("UnprocessedItems", {}).get(table, [])
                if not requests:
                    break
                time.sleep(0.05 * 2 ** attempt)
            else:
                raise RuntimeError(f"{len(requests)} deletes still unprocessed after {MAX_ATTEMPTS} attempts")
        deleted += len(keys)
    return deleted, True


def handler(event, context):
    tool = _tool_name(context)
    # Which tool ran and for which request. Arguments and results are not logged:
    # tools behind this Gateway may handle customer data.
    print(json.dumps({"tool": tool, "request_id": context.aws_request_id}))

    if tool == "list_env":
        names = [t for t in ddb.list_tables()["TableNames"] if t.startswith(PREFIX)]
        return {"environments": [n.removeprefix(PREFIX) for n in names]}
    if tool == "get_claims_store":
        env = event["environment"]
        table = ddb.describe_table(TableName=f"{PREFIX}{env}")["Table"]
        return {"environment": env, "status": table["TableStatus"]}
    if tool == "purge_claims":
        env = event["environment"]
        # Really deletes every record. No confirmation step. Deletion protection,
        # backups and point-in-time recovery do not prevent it. Only Cedar does.
        purged, complete = _purge(f"{PREFIX}{env}", context)
        return {"environment": env, "purged_records": purged, "complete": complete}
    raise ValueError(f"unhandled tool {tool}")
