"""Query Gateway policy spans and report whether a named DENY is present."""
import json
import sys
import time

from spans import query_spans

# Spans that carry a policy decision for a tool call.
WHERE = "| filter ispresent(attributes.aws.agentcore.policy.authorization_decision)"


def summarize(span: dict) -> dict:
    a = span.get("attributes", {})
    return {
        "time": span["@timestamp"],
        "traceId": span.get("traceId"),
        "name": span.get("name"),
        "decision": a.get("aws.agentcore.policy.authorization_decision"),
        "determining": a.get("aws.agentcore.policy.determining_policies"),
        "reason": a.get("aws.agentcore.policy.authorization_reason"),
        "mode": a.get("aws.agentcore.gateway.policy.mode"),
        "gateway": a.get("aws.agentcore.policy.target_resource.id"),
    }


def main(minutes: int) -> None:
    rows = [summarize(s) for s in query_spans(WHERE, start=int(time.time()) - minutes * 60)]
    print(json.dumps(rows, indent=2))
    # A deny only counts when the span names the policy that made it.
    denies = [x for x in rows if x["decision"] == "DENY" and x["determining"]]
    if denies:
        print(f"\nPASS: {len(denies)} DENY span(s) with a determining policy")
        sys.exit(0)
    print(f"\nNOT MET: no DENY with a determining policy in the last {minutes} minutes")
    sys.exit(1)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
