"""Checks over a collected pack. Each returns a status and what it found.

PASS: the evidence shows the control working. FAIL: the evidence shows it is not.
GAP: the evidence needed is not there, so nothing can be said either way.
"""

PASS, FAIL, GAP = "PASS", "FAIL", "GAP"


def gateway_listed(p):
    t = p["inventory"]["targets"]
    return (PASS, f"{len(t)} target(s) on the Gateway, {len(p['inventory']['runtimes'])} runtime(s)") \
        if t else (FAIL, "the Gateway has no targets")


def registered(p):
    """Each runtime and the Gateway are named by an approved Agent Registry record."""
    c = p["inventory"].get("catalog") or {"status": GAP, "reason": "the Agent Registry was not read"}
    if c["status"] != "OK":
        return GAP, c["reason"]
    wanted = [f"gateway {p['inventory']['gateway']['name']}"]
    wanted += [f"runtime {r['name']}" for r in p["inventory"]["runtimes"]]
    approved = {label for r in c["records"] if r["status"] == "APPROVED" for label in r["names"]}
    missing = [w for w in wanted if w not in approved]
    if missing:
        return FAIL, f"not in an approved registry record: {', '.join(missing)}"
    where = ", ".join(sorted({x["name"] for x in c["registries"]}))
    return PASS, f"{len(wanted)} of {len(wanted)} named in approved records ({where})"


def named_clients(jwt) -> bool:
    return bool(jwt and (jwt["allowedClients"] or jwt["allowedAudience"]))


def gateway_jwt(p):
    jwt = p["identity"]["gateway"]["jwt"]
    if named_clients(jwt):
        return PASS, f"JWT inbound, {len(jwt['allowedClients'])} allowed client(s)"
    return FAIL, f"inbound is {p['identity']['gateway']['authorizerType']} without a client or audience list"


def runtimes_jwt(p):
    rs = p["identity"]["runtimes"]
    if not rs:
        return GAP, "no runtimes in this Region"
    open_ = [r["name"] for r in rs if not named_clients(r["jwt"])]
    return (FAIL, f"not limited to named clients: {', '.join(open_)}") if open_ \
        else (PASS, f"{len(rs)} runtime(s), each accepting named clients only")


def engine_attached(p):
    e = p["enforcement"]
    return (PASS, f"engine {e['engineArn'].rsplit('/', 1)[-1]}") if e["engineAttached"] \
        else (FAIL, "no policy engine on the Gateway")


def forbid_present(p):
    forbids = [x for x in p["policies"] if "forbid" in x["effects"] and x["status"] == "ACTIVE"]
    applied = [x["name"] for x in forbids if x["enforcementMode"] == "ACTIVE"]
    if applied:
        return PASS, f"active forbid: {', '.join(applied)}"
    logged = [x["name"] for x in forbids]
    return FAIL, f"forbid in LOG_ONLY only: {', '.join(logged)}" if logged else "no active forbid policy"


def screens(e) -> str:
    s = e.get("screens") or {}
    return f". Screens, judged apart: {', '.join(f'{k} {v}' for k, v in sorted(s.items()))}" if s else ""


def enforced(p):
    e = p["enforcement"]
    if e["enforced"]:
        n = len(e["policies"])
        return PASS, f"Gateway mode ENFORCE, {n} permit and forbid policies ACTIVE{screens(e)}"
    off = e["policiesNotEnforced"] or "engine level"
    return FAIL, f"Gateway mode {e['gatewayMode']}, not enforced: {off}{screens(e)}"


def decisions_recorded(p):
    c = p["decisions"]["counts"]
    return (PASS, ", ".join(f"{k} {v}" for k, v in sorted(c.items()))) if c \
        else (GAP, "no policy decisions in the window")


def deny_names_policy(p):
    denies = [d for d in p["decisions"]["decisions"] if d["decision"] == "DENY"]
    named = [d for d in denies if d["determiningPolicies"]]
    if named:
        policies = sorted({x for d in named for x in d["determiningPolicies"]})
        return PASS, f"{len(named)} deny(s) naming {', '.join(policies)}"
    return (GAP, "no deny in the window") if not denies else (FAIL, "denies without a determining policy")


def calls_recorded(p):
    c = p["callers"]
    if c["status"] != "OK":
        return GAP, c["reason"]
    return PASS, f"{len(c['calls'])} call(s) in trail {c['trail']}"


def callers_identified(p):
    calls = p["callers"]["calls"]
    if not calls:
        return GAP, "no Gateway calls recorded in the window"
    missing = sum(1 for x in calls if not x["sub"])
    return (FAIL, f"{missing} call(s) without a token subject") if missing \
        else (PASS, f"every call names its token subject ({len({x['sub'] for x in calls})} distinct)")


def suppression_names_policy(p):
    c = p["callers"]
    if c["status"] != "OK":
        return GAP, c["reason"]
    withheld = [x for x in c["calls"] if x["suppressedBy"] is not None]
    named = [x for x in withheld if x["suppressedBy"]]
    if named:
        policies = sorted({s for x in named for s in x["suppressedBy"]})
        return PASS, f"{len(named)} response(s) withheld, naming {', '.join(policies)}"
    return (GAP, "no withheld response in the window") if not withheld \
        else (FAIL, "withheld responses without a named screen")


def changes_recorded(p):
    return PASS, f"{len(p['changes']['changes'])} control-plane write(s) in the window"


def _groups(p, test, what):
    gs = p["retention"]["logGroups"]
    bad = [g["name"] for g in gs if not test(g)]
    return (FAIL, f"{what}: {', '.join(bad)}") if bad else (PASS, f"{len(gs)} log group(s)")


def logs_encrypted(p):
    return _groups(p, lambda g: g["kmsKeyId"], "no customer managed key")


def logs_bounded(p):
    return _groups(p, lambda g: g["retentionInDays"], "kept forever, no retention set")


def logs_masked(p):
    return _groups(p, lambda g: g["dataProtection"] == "ACTIVATED", "no data masking")


def trail_validated(p):
    ts = p["retention"]["trails"]
    if not ts:
        return GAP, "no trail records this Gateway's calls"
    bad = [t["name"] for t in ts if not t["logFileValidation"]]
    return (FAIL, f"no file validation: {', '.join(bad)}") if bad else (PASS, "log file validation on")


CHECKS = {
    "inventory.gateway_listed": gateway_listed,
    "inventory.registered": registered,
    "identity.gateway_jwt": gateway_jwt,
    "identity.runtimes_jwt": runtimes_jwt,
    "policies.engine_attached": engine_attached,
    "policies.forbid_present": forbid_present,
    "enforcement.enforced": enforced,
    "decisions.recorded": decisions_recorded,
    "decisions.deny_names_policy": deny_names_policy,
    "callers.recorded": calls_recorded,
    "callers.identified": callers_identified,
    "callers.suppression_names_policy": suppression_names_policy,
    "changes.recorded": changes_recorded,
    "retention.logs_encrypted": logs_encrypted,
    "retention.logs_bounded": logs_bounded,
    "retention.logs_masked": logs_masked,
    "retention.trail_validated": trail_validated,
}

ORDER = {FAIL: 0, GAP: 1, PASS: 2}


def run(pack: dict) -> dict[str, tuple[str, str]]:
    return {name: check(pack) for name, check in CHECKS.items()}


def worst(statuses: list[str]) -> str:
    return min(statuses, key=ORDER.__getitem__) if statuses else GAP
