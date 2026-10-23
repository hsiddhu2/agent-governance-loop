"""Call each tool with each agent's own Gateway credential, without the model, and
print what policy decided against what it is meant to decide.

Runs only while the Gateway enforces: under LOG_ONLY every call here would run,
including the purge. Exits non-zero if any decision differs from the expected one.
"""
import json
import sys
from pathlib import Path

from discover_tools import STACK, cfn_outputs, gateway_mode, gateway_token, mcp_call

TOOL_NAMES = Path("policies/cedar/tool_names.json")
ENV = "production"
ARGS = {
    "list_env": {},
    "get_claims_store": {"environment": ENV},
    "get_claim": {"environment": ENV, "claim_id": "claim#1"},
    # A probe record that carries only an email address, which no enforced screen
    # withholds, so an allowed call is not hidden by a screen.
    "get_claim_record": {"environment": "staging", "claim_id": "probe#email"},
    "purge_claims": {"environment": "staging"},
    # A ticket with no identifier in it, so a screen has nothing to withhold.
    "get_ticket": {"environment": ENV, "ticket_id": "ticket#0"},
}
# What each agent is meant to be able to call. Everything else is denied.
ALLOWED = {
    "ops": {"list_env", "get_claims_store", "get_claim", "get_claim_record"},
    "support": {"get_ticket", "get_claim"},
}


def outcome(status: int, body: object) -> str:
    if status == 200 and isinstance(body, dict) and "result" in body:
        return "tool error" if body["result"].get("isError") else "allowed"
    error = body.get("error", {}) if isinstance(body, dict) else {}
    return f"denied ({status}, {error.get('code')}): {error.get('message', body)}"


def main() -> None:
    if gateway_mode() != "ENFORCE":
        sys.exit("The Gateway is not enforcing, so these calls would really run. Run `make enforce` first.")
    names = json.loads(TOOL_NAMES.read_text())
    outs = cfn_outputs(STACK)
    wrong = 0
    for agent, allowed in ALLOWED.items():
        token = gateway_token(outs, agent)
        for short, args in ARGS.items():
            got = outcome(*mcp_call(outs["GatewayUrl"], token, "tools/call",
                                    {"name": names[short], "arguments": args}))
            expected = "allowed" if short in allowed else "denied"
            ok = got.startswith(expected)
            wrong += not ok
            print(f"{'ok ' if ok else 'BAD'} {agent:8} {short:18} expected {expected:8} got {got}")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
