"""agentcore-evidence collect: read an AgentCore Gateway's record and write an evidence pack.

Every call it makes is a read. See iam-policy.json for the permissions it needs.
"""
import argparse
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

import boto3
import yaml

from agentcore_evidence import control_plane, records, report
from agentcore_evidence.redact import Redactor, client_ids

WINDOW = re.compile(r"^(\d+)([hd])$")


def window(since: str) -> timedelta:
    m = WINDOW.match(since)
    if not m:
        raise argparse.ArgumentTypeError("use hours or days, such as 24h or 7d")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(hours=n) if unit == "h" else timedelta(days=n)


def find_gateway(control, name_or_id: str) -> str:
    for page in control.get_paginator("list_gateways").paginate():
        for gw in page["items"]:
            if name_or_id in (gw["gatewayId"], gw["name"]):
                return gw["gatewayId"]
    sys.exit(f"no Gateway named or identified {name_or_id!r} in this Region")


def collect(session, gateway: str, region: str, start: datetime, end: datetime) -> dict:
    control = session.client("bedrock-agentcore-control", region_name=region)
    logs = session.client("logs", region_name=region)
    trail = session.client("cloudtrail", region_name=region)
    s, e = int(start.timestamp()), int(end.timestamp())

    gw = control_plane.gateway(control, find_gateway(control, gateway))
    runtimes = control_plane.runtimes(control)
    engine = control_plane.engine_id(gw)
    policies = control_plane.policies(control, engine) if engine else []
    trails = records.gateway_trails(trail, gw["gatewayArn"], region)
    return {
        "inventory": control_plane.inventory(gw, control_plane.targets(control, gw["gatewayId"]), runtimes),
        "identity": control_plane.identity(gw, runtimes),
        "policies": policies,
        "enforcement": control_plane.enforcement(gw, policies),
        "decisions": records.decisions(logs, gw["gatewayId"], s, e),
        "callers": records.callers(logs, trails, gw["gatewayArn"], s, e),
        "changes": records.changes(trail, start, end),
        "retention": records.retention(logs, trails, [r["agentRuntimeId"] for r in runtimes]),
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="agentcore-evidence")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="write an evidence pack for one Gateway")
    c.add_argument("--gateway", required=True, help="Gateway name or id")
    c.add_argument("--region", required=True)
    c.add_argument("--since", type=window, default=window("24h"), help="look-back window, such as 24h or 7d")
    c.add_argument("--out", type=Path, required=True, help="an empty or new directory")
    c.add_argument("--redact", action="store_true",
                   help="replace account ids, client ids, pool ids, emails, addresses and session names")
    c.add_argument("--controls", type=Path, help="your own controls file in place of the bundled one")
    c.add_argument("--profile", help="AWS profile to read with")
    args = p.parse_args(argv)

    if args.out.exists() and any(args.out.iterdir()):
        sys.exit(f"{args.out} is not empty. A pack is written to an empty directory so no old file mixes in.")
    controls_text = (args.controls.read_text() if args.controls
                     else resources.files("agentcore_evidence").joinpath("controls.yaml").read_text())
    controls = yaml.safe_load(controls_text)

    session = boto3.Session(profile_name=args.profile)
    end = datetime.now(UTC)
    start = end - args.since
    t0 = time.time()
    pack = collect(session, args.gateway, args.region, start, end)
    run = {
        "gateway": pack["inventory"]["gateway"]["name"],
        "region": args.region,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "collectedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "caller": session.client("sts", region_name=args.region).get_caller_identity()["Arn"],
        "redacted": args.redact,
    }
    if args.redact:
        r = Redactor({"client": client_ids(pack)}, origin=start)
        pack, run = r.value(pack), r.value(run)
    results = report.write_pack(args.out, pack, controls, run)
    counts = {}
    for status, _ in results.values():
        counts[status] = counts.get(status, 0) + 1
    tally = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"wrote {args.out} in {time.time() - t0:.0f}s: {tally}")


if __name__ == "__main__":
    main()
