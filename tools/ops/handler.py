import json
import os
import time

import boto3

ddb = boto3.client("dynamodb")
PREFIX = os.environ["TABLE_PREFIX"]
MAX_ATTEMPTS = 6
TOOLS = ("list_env", "get_claims_store", "get_claim", "get_claim_record", "purge_claims")


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


def _claim(env: str, claim_id: str) -> dict:
    item = ddb.get_item(TableName=f"{PREFIX}{env}", Key={"pk": {"S": claim_id}}).get("Item")
    if item is None:
        raise ValueError(f"no claim {claim_id} in {env}")
    return item


def _text(attribute: dict | None) -> dict:
    return {k: v["S"] for k, v in (attribute or {}).get("M", {}).items()}


def _statement(title: str, fields: dict) -> str:
    """A statement as a claim file holds it: one labelled line per field."""
    if not fields:
        return "No statement on file."
    return "\n".join([title, *(f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in fields.items())])


def get_claim(env: str, claim_id: str) -> dict:
    """What a claims agent needs to answer status questions, and nothing that names a person.

    This is the production shape: the API decides what leaves the store, so the agent
    never holds an identifier it could repeat. The insured is reduced to what support
    staff use to confirm identity on a call.
    """
    item = _claim(env, claim_id)
    holder = _text(item.get("policyholder"))
    return {
        "claim_id": claim_id,
        "policy_number": item["policy_number"]["S"],
        "status": item["status"]["S"],
        "claim_type": item["claim_type"]["S"],
        "amount": item["amount"]["N"],
        "insured_ssn_last4": holder.get("ssn", "")[-4:],
        "insured_birth_year": holder.get("date_of_birth", "")[-4:],
    }


def get_claim_record(env: str, claim_id: str) -> dict:
    """The whole claim file, as stored.

    Deliberately not minimized: a tool like this hands the agent every identifier and
    health detail in the record. It exists to show what a guardrail at the Gateway does
    and does not catch when an API gets this wrong. get_claim is the shape to copy.
    """
    item = _claim(env, claim_id)
    return {
        "claim_id": claim_id,
        "status": item["status"]["S"],
        "policyholder": _statement("Policyholder statement", _text(item.get("policyholder"))),
        "health": _statement("Attending physician statement", _text(item.get("health"))),
    }


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
    if tool == "get_claim":
        return get_claim(event["environment"], event["claim_id"])
    if tool == "get_claim_record":
        return get_claim_record(event["environment"], event["claim_id"])
    if tool == "purge_claims":
        env = event["environment"]
        # Really deletes every record. No confirmation step. Deletion protection,
        # backups and point-in-time recovery do not prevent it. Only Cedar does.
        purged, complete = _purge(f"{PREFIX}{env}", context)
        return {"environment": env, "purged_records": purged, "complete": complete}
    raise ValueError(f"unhandled tool {tool}")
