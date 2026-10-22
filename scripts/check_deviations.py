"""Check that every acknowledged rule finding is disclosed in the README.

A finding acknowledged in code is a decision not to meet a rule. Each such rule must
appear in the README's deviations table, and the table may not list rules that are no
longer acknowledged. Reads the acknowledgements cdk synth records in cdk.out, so run it
after a synth with -c nag=true.
"""
import json
import re
import sys
from pathlib import Path

README = Path("README.md")
SECTION = "## Deviations from production"
# The rule id is the backticked first cell of each table row.
RULE = re.compile(r"^\|\s*`([^`]+)`", re.M)


def acknowledged_rules(cdk_out: Path) -> set[str]:
    rules = set()
    for f in cdk_out.glob("*.metadata.json"):
        for entries in json.loads(f.read_text()).values():
            for e in entries:
                if e.get("type") == "aws:cdk:acknowledged-rules":
                    # Ids look like "AwsSolutions::AwsSolutions-IAM5[Resource::*]".
                    rules |= {k.split("::", 1)[-1].split("[", 1)[0] for k in e["data"]}
    return rules


def disclosed_rules(readme: str) -> set[str]:
    if SECTION not in readme:
        return set()
    body = readme.split(SECTION, 1)[1].split("\n## ", 1)[0]
    return set(RULE.findall(body))


def problems(acknowledged: set[str], disclosed: set[str]) -> list[str]:
    out = [f"acknowledged but not in the README deviations table: {r}"
           for r in sorted(acknowledged - disclosed)]
    out += [f"in the README deviations table but no longer acknowledged: {r}"
            for r in sorted(disclosed - acknowledged)]
    return out


def main() -> None:
    found = problems(acknowledged_rules(Path("cdk.out")), disclosed_rules(README.read_text()))
    if found:
        sys.exit("FAIL:\n  " + "\n  ".join(found))
    print("deviations: every acknowledged rule is disclosed in the README")


if __name__ == "__main__":
    main()
