"""Check that the app synthesizes the same stacks with and without rendered
policies, which `make discover` writes.

Policies are rendered from the live Gateway, so the policy stack's contents depend
on local files. Nothing else may. This synthesizes once with no rendered policies
and compares every other stack's template with the normal synth in cdk.out.
A difference means a deploy order would matter again, so the check fails.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

POLICY_STACK = "AglPolicy"


def main(context: list[str]) -> None:
    normal = Path("cdk.out")
    if not any(normal.glob("*.template.json")):
        sys.exit("cdk.out has no templates. Run cdk synth first.")

    with tempfile.TemporaryDirectory() as tmp:
        no_policies = Path(tmp, "policies")
        no_policies.mkdir()
        out = Path(tmp, "out")
        subprocess.run(
            ["cdk", "synth", "--quiet", "-o", str(out), "-c", f"policies_dir={no_policies}", *context],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        names = sorted(p.name for p in normal.glob("*.template.json"))
        if names != sorted(p.name for p in out.glob("*.template.json")):
            sys.exit("FAIL: the set of stacks changes when no policies are rendered")
        changed = [n for n in names
                   if not n.startswith(POLICY_STACK)
                   and Path(normal, n).read_bytes() != Path(out, n).read_bytes()]

    if changed:
        sys.exit(f"FAIL: these templates change when no policies are rendered: {changed}")
    print(f"stable synth: {len(names) - 1} stack templates identical with and without rendered policies")


if __name__ == "__main__":
    main(sys.argv[1:])
