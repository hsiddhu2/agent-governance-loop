"""Run a CloudWatch Logs Insights query to completion."""
import time

QUERY_TIMEOUT_SECONDS = 120


def run_query(logs, log_group: str, query: str, start: int, end: int, limit: int) -> list[dict]:
    """Return each result row as a dict of field to value. A query that does not complete raises."""
    q = logs.start_query(logGroupName=log_group, startTime=start, endTime=end,
                         queryString=query, limit=limit)
    give_up_at = time.time() + QUERY_TIMEOUT_SECONDS
    while True:
        r = logs.get_query_results(queryId=q["queryId"])
        if r["status"] not in ("Scheduled", "Running"):
            break
        if time.time() > give_up_at:
            raise RuntimeError(f"Logs Insights query on {log_group} still running after "
                               f"{QUERY_TIMEOUT_SECONDS}s")
        time.sleep(1)
    if r["status"] != "Complete":
        raise RuntimeError(f"Logs Insights query on {log_group} ended with status {r['status']}")
    return [{f["field"]: f["value"] for f in row} for row in r["results"]]
