"""Write the pack: one file per question, a summary against the controls, and a manifest."""
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from agentcore_evidence import __version__, checks

# Which file holds the evidence behind each kind of check.
EVIDENCE = {
    "inventory": "inventory.json",
    "identity": "identity.json",
    "policies": "policies.json",
    "enforcement": "enforcement.json",
    "decisions": "decisions.json",
    "callers": "callers.json",
    "changes": "changes.json",
    "retention": "retention.json",
}
NOTE = ("This pack supports evidence for the asks below. It does not show compliance with "
        "any of them: each source asks for more than an account can show, and compliance is "
        "decided over a whole program.")


def write_json(out: Path, name: str, data) -> None:
    (out / name).write_text(json.dumps(data, indent=2, default=str) + "\n")


def write_pack(out: Path, pack: dict, controls: list[dict], run: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    cedar = out / "policies"
    cedar.mkdir(exist_ok=True)
    # Each digest is of the statement as written here, after any redaction, so a reader
    # can check it against the file in the pack.
    # A policy with no statement, such as one made from a policy generation, gets no file.
    digests = {}
    for p in pack["policies"]:
        if p["statement"] is None:
            digests[p["name"]] = None
            continue
        path = cedar / f"{p['name']}.cedar"
        path.write_text(p["statement"] + "\n", encoding="utf-8")
        digests[p["name"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(out, "policies.json", [{**{k: v for k, v in p.items() if k != "statement"},
                                       "sha256": digests[p["name"]]} for p in pack["policies"]])
    for key, name in EVIDENCE.items():
        if key != "policies":
            write_json(out, name, pack[key])

    results = checks.run(pack)
    write_json(out, "checks.json", {k: {"status": s, "finding": f} for k, (s, f) in results.items()})
    (out / "summary.md").write_text(summary(controls, results, run, unmatched(pack)))
    manifest = {
        "tool": "agentcore-evidence",
        "version": __version__,
        **run,
        "files": {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in sorted(out.rglob("*")) if f.is_file() and f.name != "manifest.json"},
    }
    write_json(out, "manifest.json", manifest)
    return results


OFFSET = re.compile(r"^T([+-])(?:(\d+)d )?(\d{2}):(\d{2}):(\d{2})$")


def instant(stamp: str):
    """A time from the pack, as written or as a redacted offset, in a form that sorts."""
    m = OFFSET.match(stamp)
    if not m:
        return datetime.fromisoformat(stamp)
    sign, days, h, mi, s = m.groups()
    t = timedelta(days=int(days or 0), hours=int(h), minutes=int(mi), seconds=int(s))
    return -t if sign == "-" else t


def unmatched(pack: dict) -> str | None:
    """A sentence when the trail holds fewer calls than there are decisions, else None.

    A trail records only from when it was created, so decisions before its first event
    have no call to match.
    """
    # Only tool calls are decided one by one. A tools/list call has no decision of its own.
    decisions = pack["decisions"]["decisions"]
    calls = [c for c in pack["callers"]["calls"] if c.get("method") == "tools/call"]
    if pack["callers"]["status"] != "OK" or len(decisions) <= len(calls):
        return None
    note = f"{len(decisions)} decisions but {len(calls)} recorded tool call{'s' if len(calls) != 1 else ''}."
    earliest = min((d["time"] for d in decisions if d["time"]), key=instant, default=None)
    first = min((c["time"] for c in calls if c["time"]), key=instant, default=None)
    if earliest and first and instant(first) > instant(earliest):
        note += (f" The trail's first recorded event, {first}, is later than the earliest decision, "
                 f"{earliest}, so earlier decisions have no matching call.")
    return note


def summary(controls: list[dict], results: dict, run: dict, note: str | None = None) -> str:
    lines = [
        "# Evidence pack",
        "",
        f"Gateway `{run['gateway']}` in {run['region']}. Window {run['start']} to {run['end']}.",
        f"Collected {run['collectedAt']} by `{run['caller']}`.",
        *([note] if note else []),
        "",
        NOTE,
        "",
        "PASS: the evidence shows the control working. FAIL: it shows the control is not. "
        "GAP: the evidence needed is not there.",
        "",
        "## Controls",
        "",
        "| Ask | Status | Checks | Limits |",
        "|---|---|---|---|",
    ]
    for c in controls:
        status = checks.worst([results[x][0] for x in c["checks"]])
        lines.append(f"| {c['ask']} | **{status}** | {', '.join(c['checks'])} | {c.get('limits', '')} |")
    lines += ["", "## Checks", "", "| Check | Status | Finding | Evidence |", "|---|---|---|---|"]
    for name, (status, finding) in results.items():
        lines.append(f"| {name} | {status} | {finding} | `{EVIDENCE[name.split('.')[0]]}` |")
    lines += ["", "## Sources", ""]
    for c in controls:
        for s in c["sources"]:
            lines.append(f"- {c['ask']}: {s['source']}, {s['section']}: \"{s['quote']}\" {s['url']}")
    return "\n".join(lines) + "\n"
