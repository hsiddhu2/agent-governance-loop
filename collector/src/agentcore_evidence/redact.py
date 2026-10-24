"""Replace identifiers with stable placeholders, so a pack can be shared outside the account.

The same value always becomes the same placeholder, so a client that appears in the
Gateway's allowed list and in the trail is still visibly the same client.

Given a start time, timestamps become offsets from it, such as T+00:15:32 or
T-6d 02:13:00. Order and spacing stay readable, and the pack no longer says when the
system ran.
"""
import re
from datetime import UTC, datetime

PATTERNS = [
    ("account", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    ("user-pool", re.compile(r"\b[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]
# The session part of an assumed-role ARN is often a person's sign-in name.
SESSION = re.compile(r"(assumed-role/[^/\s\"]+/)([^\s\"]+)")
# IAM Identity Center names each role AWSReservedSSO_<permission set>_<unique suffix>. The
# suffix is generated per account and assignment, so it identifies the organization.
SSO_ROLE = re.compile(r"(AWSReservedSSO_[\w+=,.@-]+_)([0-9a-f]{16})\b")
KEEP = {"sha256"}
TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")


def offset(stamp: str, origin: datetime) -> str:
    t = datetime.fromisoformat(stamp)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    seconds = int((t - origin).total_seconds())
    sign, seconds = ("+", seconds) if seconds >= 0 else ("-", -seconds)
    days, rest = divmod(seconds, 86400)
    clock = f"{rest // 3600:02d}:{rest % 3600 // 60:02d}:{rest % 60:02d}"
    return f"T{sign}{days}d {clock}" if days else f"T{sign}{clock}"


class Redactor:
    def __init__(self, known: dict[str, list[str]] | None = None, origin: datetime | None = None):
        self.origin = origin
        self.names: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        # Exact values such as client ids, which have no shape a pattern could find.
        self.exact = [(kind, v) for kind, values in (known or {}).items() for v in values if v]

    def placeholder(self, kind: str, value: str) -> str:
        if value not in self.names:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.names[value] = f"<{kind}-{self.counts[kind]}>"
        return self.names[value]

    def text(self, s: str) -> str:
        if self.origin:
            s = TIMESTAMP.sub(lambda m: offset(m.group(0), self.origin), s)
        for kind, value in self.exact:
            if value in s:
                s = s.replace(value, self.placeholder(kind, value))
        s = SESSION.sub(lambda m: m.group(1) + self.placeholder("session", m.group(2)), s)
        s = SSO_ROLE.sub(lambda m: m.group(1) + self.placeholder("sso-role", m.group(2)), s)
        for kind, pattern in PATTERNS:
            s = pattern.sub(lambda m, k=kind: self.placeholder(k, m.group(0)), s)
        return s

    def value(self, v):
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            # A digest is not an identifier, and a run of its digits could look like one.
            return {self.text(k): x if k in KEEP else self.value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.value(x) for x in v]
        return v


def client_ids(pack: dict) -> list[str]:
    """Every client id the pack names, from authorizers and from the trail."""
    ids = set()
    ident = pack["identity"]
    for jwt in [ident["gateway"]["jwt"], *(r["jwt"] for r in ident["runtimes"])]:
        ids.update((jwt or {}).get("allowedClients", []))
    for call in pack["callers"]["calls"]:
        ids.update(x for x in (call["sub"], call["clientId"]) if x)
    return sorted(ids, key=len, reverse=True)
