import json
import os

import boto3

ddb = boto3.client("dynamodb")
PREFIX = os.environ["TABLE_PREFIX"]
TOOLS = ("list_env", "get_store", "delete_store")


def _tool_name(context) -> str:
    # The Gateway passes the full, target-prefixed tool name. Match on the known
    # tool names rather than splitting on a separator, which is not stable.
    full = context.client_context.custom["bedrockAgentCoreToolName"]
    matches = [t for t in TOOLS if full.endswith(t)]
    if not matches:
        raise ValueError(f"unknown tool {full}")
    return max(matches, key=len)


def handler(event, context):
    # Logged until the event shape is confirmed in the account.
    custom = getattr(getattr(context, "client_context", None), "custom", None)
    print(json.dumps({"event": event, "client_context_custom": custom}, default=str))

    tool = _tool_name(context)
    if tool == "list_env":
        names = [t for t in ddb.list_tables()["TableNames"] if t.startswith(PREFIX)]
        return {"environments": [n.removeprefix(PREFIX) for n in names]}
    if tool == "get_store":
        env = event["environment"]
        table = ddb.describe_table(TableName=f"{PREFIX}{env}")["Table"]
        return {"environment": env, "status": table["TableStatus"],
                "items": table.get("ItemCount", 0)}
    if tool == "delete_store":
        env = event["environment"]
        # Really deletes the table. No confirmation step. Only Cedar prevents it.
        ddb.delete_table(TableName=f"{PREFIX}{env}")
        return {"deleted": env}
    raise ValueError(f"unhandled tool {tool}")
