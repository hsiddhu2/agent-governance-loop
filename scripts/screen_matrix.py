"""Measure what each output screen catches, one kind of field at a time.

Each probe record carries a single field from a full claim file, so a screen that fires
on it fired on that field. Every probe is read through get_claim_record with the ops
agent's own credential, without the model, several times. Each call is sent with its
own trace id, which the Gateway keeps, so its policy decision is found exactly in the
spans. A screen in ACTIVE mode withholds the response and the caller's error names it.
A screen in LOG_ONLY mode withholds nothing, and its decision record says it matched.

Writes the raw calls and decisions to evidence/ and, with --doc, the table to a file.
Runs only while the Gateway enforces.
"""
import argparse
import json
import re
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from discover_tools import STACK, cfn_outputs, gateway_mode, gateway_token
from spans import query_spans
from synthetic import probes

TOOL_NAMES = Path("policies/tool_names.json")
TEMPLATES = Path("policies/guardrails")
TOOL = "get_claim_record"
SPAN_WAIT_SECONDS = 600

# The category a detector would need to find each field. None: the policy language has
# no category for it (see docs/guardrail-policies.md, "What cannot be screened").
EXPECTED = {
    "name": "NAME", "date_of_birth": None, "ssn": "US_SOCIAL_SECURITY_NUMBER", "address": "ADDRESS",
    "phone": "PHONE", "email": "EMAIL", "driver_license": "DRIVER_ID", "passport": "US_PASSPORT_NUMBER",
    "bank_account": "US_BANK_ACCOUNT_NUMBER", "bank_routing": "US_BANK_ROUTING_NUMBER",
    "card": "CREDIT_DEBIT_CARD_NUMBER", "medical_record_number": None, "health_plan_member_id": None,
    "attending_physician": "NAME", "diagnosis": None, "icd10": None, "medications": None,
    "admitted": None, "discharged": None, "clinical_note": None,
}
CATEGORY = re.compile(r'contains\("([A-Z_]+)"\)')
TOOL_PLACEHOLDER = re.compile(r"\{\{TOOL:(\w+)\}\}")
WITHHELD_BY = re.compile(r"denied due to (.+?)\]?$")
SCORES = "guardrails.sensitiveInformation.scores"
# matched_policies and log_only_matched_policies, not mismatched_policies.
MATCHED = re.compile(r"(?<!mis)matched_policies$")


def screens_on(tool: str, templates: Path = TEMPLATES) -> dict[str, set[str]]:
    """Each screen on `tool` and the categories it tests, read from the policy templates."""
    found = {}
    for tmpl in sorted(templates.glob("*.cedar.tmpl")):
        text = tmpl.read_text()
        if "suppressOutput" in text and tool in TOOL_PLACEHOLDER.findall(text):
            found[tmpl.name.removesuffix(".cedar.tmpl")] = set(CATEGORY.findall(text))
    return found


def base(policy_id: str) -> str:
    """A live policy id is its name plus a suffix the service adds."""
    return policy_id.rsplit("-", 1)[0]


def withheld_by(status: int, body: object) -> list[str]:
    """The screens a withheld response names. Empty when it was not withheld."""
    message = (body.get("error", {}) if isinstance(body, dict) else {}).get("message", "")
    found = WITHHELD_BY.search(message) if status == 403 else None
    return sorted({base(n.strip()) for n in found.group(1).split(",") if n.strip()}) if found else []


def decision(spans: list[dict]) -> dict:
    """What the output-phase decision says: screens that matched and what was detected."""
    matched, detected = set(), set()
    for s in spans:
        for key, value in s.get("attributes", {}).items():
            if key.endswith(SCORES):
                for policy, category, _score in value:
                    matched.add(base(policy))
                    detected.add(category)
            elif MATCHED.search(key) and isinstance(value, list):
                matched.update(base(p) for p in value)
    return {"matched": sorted(matched), "detected": sorted(detected)}


def classify(expected: str | None, covering: list[str], runs: list[dict]) -> str:
    """One word for what the screens did with a field over every run."""
    n = len(runs)
    withheld = sum(1 for r in runs if set(r["withheldBy"]) & set(covering))
    logged = sum(1 for r in runs if set(r["matched"]) & set(covering) and not r["withheldBy"])
    if expected is None:
        other = sum(1 for r in runs if r["matched"] or r["withheldBy"])
        return "no category exists" + (f", other screen matched {other}/{n}" if other else "")
    if not covering:
        return "no screen tests its category"
    if withheld == n:
        return f"caught, withheld {n}/{n}"
    if withheld + logged == n:
        return f"caught in LOG_ONLY {logged}/{n}" + (f", withheld {withheld}/{n}" if withheld else "")
    return f"missed {n - withheld - logged}/{n}"


def call(url: str, token: str, name: str, claim_id: str) -> dict:
    trace = secrets.token_hex(16)
    resp = requests.post(url, timeout=30, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "traceparent": f"00-{trace}-{secrets.token_hex(8)}-01",
    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": name, "arguments": {"environment": "staging", "claim_id": claim_id}}})
    try:
        body = resp.json()
    except ValueError:
        events = [line[5:] for line in resp.text.splitlines() if line.startswith("data:")]
        body = json.loads(events[-1]) if events else resp.text
    return {"traceId": trace, "status": resp.status_code, "withheldBy": withheld_by(resp.status_code, body)}


def wait_for_spans(calls: list[dict], start: int) -> dict[str, list[dict]]:
    """The policy decision spans for each call, once each has every span it will get.

    A call is decided on its request and again on its response. When an ACTIVE screen
    withholds the response, only the request decision is written to the spans. The
    withhold itself shows in the caller's error, the tool span and CloudTrail.
    """
    traces = [c["traceId"] for c in calls]
    expected = {c["traceId"]: 1 if c["withheldBy"] else 2 for c in calls}
    give_up_at = time.time() + SPAN_WAIT_SECONDS
    while True:
        found: dict[str, list[dict]] = {}
        for i in range(0, len(traces), 20):
            ids = ", ".join(f'"{t}"' for t in traces[i:i + 20])
            for s in query_spans(f'| filter name = "AgentCore.Policy.AuthorizeAction" and traceId in [{ids}]',
                                 start=start, limit=200):
                found.setdefault(s["traceId"], []).append(s)
        missing = [t for t in traces if len(found.get(t, [])) < expected[t]]
        if not missing:
            return found
        if time.time() > give_up_at:
            sys.exit(f"{len(missing)} call(s) have no decision yet. Run again later with --calls.")
        time.sleep(20)


def table(rows: list[dict]) -> str:
    out = ["| Field | Category needed | Screen that tests it | Detected | Result |", "|---|---|---|---|---|"]
    for r in rows:
        # A withheld response has no output decision span, so what was detected is not recorded.
        detected = ", ".join(r["detected"]) or ("not recorded" if "withheld" in r["result"] else "-")
        out.append(f"| `{r['field']}` | {r['expected'] or 'none'} | {', '.join(r['covering']) or '-'} | "
                   f"{detected} | {r['result']} |")
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--doc", type=Path, help="also write the table to this file")
    p.add_argument("--calls", type=Path, help="read the decisions for calls an earlier run sent")
    a = p.parse_args()

    screens = screens_on(TOOL)
    if a.calls:
        saved = json.loads(a.calls.read_text())
        calls, start, out = saved["calls"], saved["start"], a.calls
    else:
        if gateway_mode() != "ENFORCE":
            sys.exit("The Gateway is not enforcing. Run `make enforce` first.")
        outs = cfn_outputs(STACK)
        name = json.loads(TOOL_NAMES.read_text())[TOOL]
        token = gateway_token(outs, "ops")
        start = int(time.time()) - 60
        calls = []
        for probe in probes():
            field = probe["pk"].removeprefix("probe#")
            for _ in range(a.runs):
                calls.append({"field": field, **call(outs["GatewayUrl"], token, name, probe["pk"])})
        # Saved before waiting, so the decisions can be read later with --calls.
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = Path("evidence") / f"screen-matrix-{stamp}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"start": start, "calls": calls}, indent=2) + "\n")
        print(f"{len(calls)} calls sent, saved to {out}. Waiting for their decisions.", flush=True)
    spans = wait_for_spans(calls, start)
    for c in calls:
        c.update(decision(spans[c["traceId"]]))

    rows = []
    for field, expected in EXPECTED.items():
        runs = [c for c in calls if c["field"] == field]
        covering = sorted(s for s, cats in screens.items() if expected in cats)
        rows.append({"field": field, "expected": expected, "covering": covering,
                     "detected": sorted({d for r in runs for d in r["detected"]}),
                     "result": classify(expected, covering, runs)})

    out.write_text(json.dumps({"start": start, "screens": {k: sorted(v) for k, v in screens.items()},
                               "calls": calls, "rows": rows}, indent=2) + "\n")
    print(table(rows))
    print(f"\nraw calls and decisions: {out}")
    if a.doc:
        a.doc.write_text(table(rows) + "\n")


if __name__ == "__main__":
    main()
