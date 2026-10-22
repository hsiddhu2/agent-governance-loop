"""Check that no stack output carries a secret.

Stack outputs are readable by anyone allowed to describe the stack. CDK also turns a
reference from one stack to another into an output, so passing a secret between stacks
publishes it. This fails when any output reads a resource attribute that names a secret,
other than its ARN. Reads the templates in cdk.out, so run it after a synth.
"""
import json
import re
import sys
from pathlib import Path

SECRET = re.compile(r"secret", re.I)
ARN = re.compile(r"arn$", re.I)


def attributes(value) -> list[str]:
    """Every attribute name an output value reads with Fn::GetAtt."""
    found = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "Fn::GetAtt":
                found.append(inner[1] if isinstance(inner, list) else inner.split(".", 1)[1])
            else:
                found += attributes(inner)
    elif isinstance(value, list):
        for inner in value:
            found += attributes(inner)
    return found


def secret_outputs(template: dict) -> list[str]:
    return [name for name, out in template.get("Outputs", {}).items()
            if any(SECRET.search(a) and not ARN.search(a) for a in attributes(out.get("Value")))]


def main() -> None:
    found = [f"{f.name}: {name}" for f in sorted(Path("cdk.out").glob("*.template.json"))
             for name in secret_outputs(json.loads(f.read_text()))]
    if found:
        sys.exit("FAIL: stack outputs carry a secret:\n  " + "\n  ".join(found))
    print("outputs: no stack output carries a secret")


if __name__ == "__main__":
    main()
