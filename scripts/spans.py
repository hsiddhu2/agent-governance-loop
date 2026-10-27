"""Read spans from CloudWatch with their attributes intact.

Logs Insights is used only to find the spans. Insights can flatten list attributes,
so each span is parsed from its raw JSON. Policy spans carry lists (allowed tools, denied tools, determining
policies), and an empty list is often the very thing a check is looking for.
"""
import json
import time

import boto3

REGION = "us-east-1"
LOG_GROUP = "aws/spans"


def query_spans(where: str, start: int, end: int | None = None, limit: int = 20) -> list[dict]:
    """Return the newest spans matching `where`, newest first.

    `where` is one or more Logs Insights `| filter ...` clauses. `start` and `end`
    are epoch seconds. Each span is returned as parsed JSON, with the ingestion
    time added under `@timestamp`. A query that does not complete raises.
    """
    logs = boto3.client("logs", region_name=REGION)
    query = f"fields @timestamp, @message\n{where}\n| sort @timestamp desc\n| limit {limit}"
    q = logs.start_query(logGroupName=LOG_GROUP, startTime=start,
                         endTime=end or int(time.time()), queryString=query)
    while True:
        r = logs.get_query_results(queryId=q["queryId"])
        if r["status"] not in ("Scheduled", "Running"):
            break
        time.sleep(1)
    if r["status"] != "Complete":
        raise RuntimeError(f"Logs Insights query ended with status {r['status']}")

    spans = []
    for row in r["results"]:
        fields = {f["field"]: f["value"] for f in row}
        span = json.loads(fields["@message"])
        span["@timestamp"] = fields["@timestamp"]
        spans.append(span)
    return spans
