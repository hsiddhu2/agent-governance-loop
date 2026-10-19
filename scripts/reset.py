"""Put the data stores back after a scenario run, then reseed.

A table deleted by a tool call is gone from DynamoDB, but CloudFormation still lists it,
so a plain redeploy reports no changes and recreates nothing. Each table has its own
stack, so only the stack of a missing table is destroyed and deployed again. The other
table is left as it is. No other stack depends on a data stack.
"""
import os
import subprocess
import sys

import boto3

# Table name -> the stack that owns it. Matches the data stacks in infra/app.py.
STACKS = {
    "agl-claims-staging": "AglDataStaging",
    "agl-claims-production": "AglDataProduction",
}
ddb = boto3.client("dynamodb", region_name="us-east-1")


def is_present(name: str) -> bool:
    try:
        status = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
    except ddb.exceptions.ResourceNotFoundException:
        return False
    if status == "DELETING":
        # A delete that just ran is still in progress; wait so the rebuild does not collide with it.
        ddb.get_waiter("table_not_exists").wait(TableName=name)
        return False
    return True


def cdk(*args: str) -> None:
    subprocess.run(["cdk", *args, "-c", f"expires={os.environ['EXPIRES']}"], check=True)


missing = [t for t in STACKS if not is_present(t)]
if missing:
    if not os.environ.get("EXPIRES"):
        sys.exit("EXPIRES is not set. Run this through `make reset`.")
for table in missing:
    stack = STACKS[table]
    print(f"missing: {table}; rebuilding {stack}")
    cdk("destroy", stack, "--exclusively", "--force")
    # Same rule pack as every other deploy.
    cdk("deploy", stack, "--exclusively", "--require-approval", "never", "-c", "nag=true")
subprocess.run([sys.executable, "scripts/seed.py"], check=True)
