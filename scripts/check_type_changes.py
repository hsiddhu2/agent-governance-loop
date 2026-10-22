"""Check that a deploy does not change the type of any existing resource.

CloudFormation cannot change a resource's type under the same logical id. It finds
out only while running the update, and the stack rolls back. This compares each
named stack's template in cdk.out with the template the live stack was deployed
from and fails on any logical id whose type differs. A stack that does not exist
yet passes. Run it after a synth, then deploy that same cdk.out.
"""
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"


def resource_types(template: dict) -> dict[str, str]:
    return {lid: r["Type"] for lid, r in template.get("Resources", {}).items()}


def type_changes(new: dict, live: dict) -> list[str]:
    """Logical ids present in both templates whose resource type differs."""
    before, after = resource_types(live), resource_types(new)
    return [f"{lid}: {before[lid]} -> {after[lid]}"
            for lid in sorted(before.keys() & after.keys()) if before[lid] != after[lid]]


def live_template(cfn, stack: str) -> dict | None:
    try:
        body = cfn.get_template(StackName=stack, TemplateStage="Original")["TemplateBody"]
    except ClientError as e:
        if "does not exist" in e.response["Error"]["Message"]:
            return None
        raise
    return body if isinstance(body, dict) else json.loads(body)


def main(stacks: list[str]) -> None:
    if not stacks:
        sys.exit("Name the stacks to check.")
    cfn = boto3.client("cloudformation", region_name=REGION)
    found = []
    for stack in stacks:
        path = Path("cdk.out", f"{stack}.template.json")
        if not path.exists():
            sys.exit(f"{path} is missing. Run cdk synth first.")
        live = live_template(cfn, stack)
        if live is None:
            print(f"type changes: {stack} is new")
            continue
        found += [f"{stack} {c}" for c in type_changes(json.loads(path.read_text()), live)]
    if found:
        sys.exit("FAIL: these resources would change type. Give each a new construct id:\n  "
                 + "\n  ".join(found))
    print(f"type changes: none in {', '.join(stacks)}")


if __name__ == "__main__":
    main(sys.argv[1:])
