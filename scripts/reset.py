"""Put the data stores back. Redeploys a deleted table, then reseeds."""
import os
import subprocess
import sys

import boto3

ddb = boto3.client("dynamodb", region_name="us-east-1")
existing = set(ddb.list_tables()["TableNames"])
if not {"agl-staging", "agl-production"} <= existing:
    expires = os.environ.get("EXPIRES")
    if not expires:
        sys.exit("EXPIRES is not set. Run this through `make reset`.")
    print("a table is missing, redeploying AglData")
    subprocess.run(["cdk", "deploy", "AglData", "--require-approval", "never",
                    "-c", f"expires={expires}"], check=True)
subprocess.run([sys.executable, "scripts/seed.py"], check=True)
