"""Write the pack: one file per question, a summary against the controls, and a manifest."""
import hashlib
import json
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
    for p in pack["policies"]:
        (cedar / f"{p['name']}.cedar").write_text(p["statement"] + "\n")
    write_json(out, "policies.json", [{k: v for k, v in p.items() if k != "statement"}
                                      for p in pack["policies"]])
    for key, name in EVIDENCE.items():
        if key != "policies":
            write_json(out, name, pack[key])

    results = checks.run(pack)
    write_json(out, "checks.json", {k: {"status": s, "finding": f} for k, (s, f) in results.items()})
    (out / "summary.md").write_text(summary(controls, results, run))
    manifest = {
        "tool": "agentcore-evidence",
        "version": __version__,
        **run,
        "files": {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in sorted(out.rglob("*")) if f.is_file() and f.name != "manifest.json"},
    }
    write_json(out, "manifest.json", manifest)
    return results


def summary(controls: list[dict], results: dict, run: dict) -> str:
    lines = [
        "# Evidence pack",
        "",
        f"Gateway `{run['gateway']}` in {run['region']}. Window {run['start']} to {run['end']}.",
        f"Collected {run['collectedAt']} by `{run['caller']}`.",
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
