"""Query Gateway policy spans and report whether a named DENY is present."""
import json
import sys
import time

import boto3

LOG_GROUP = "aws/spans"
QUERY = """
fields @timestamp, traceId, name,
  attributes.aws.agentcore.policy.authorization_decision as decision,
  attributes.aws.agentcore.policy.determining_policies as determining,
  attributes.aws.agentcore.policy.authorization_reason as reason,
  attributes.aws.agentcore.gateway.policy.mode as mode,
  attributes.aws.agentcore.policy.target_resource.id as gateway
| filter ispresent(attributes.aws.agentcore.policy.authorization_decision)
| sort @timestamp desc
| limit 20
"""


def main(minutes: int) -> None:
    logs = boto3.client("logs", region_name="us-east-1")
    end = int(time.time())
    q = logs.start_query(logGroupName=LOG_GROUP, startTime=end - minutes * 60,
                         endTime=end, queryString=QUERY)
    while True:
        r = logs.get_query_results(queryId=q["queryId"])
        if r["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1)

    rows = [{f["field"]: f["value"] for f in row} for row in r["results"]]
    print(json.dumps(rows, indent=2))
    denies = [x for x in rows if x.get("decision") == "DENY" and x.get("determining")]
    if denies:
        print(f"\nPASS: {len(denies)} DENY span(s) with a determining policy")
        sys.exit(0)
    print(f"\nNOT MET: no DENY with a determining policy in the last {minutes} minutes")
    sys.exit(1)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
