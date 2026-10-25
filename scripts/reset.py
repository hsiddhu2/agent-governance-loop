"""Put the claim records and tickets back after a scenario run.

A purge deletes records, not tables: the tables have deletion protection. So a reset
only checks that the four tables, claims and tickets in each environment, are there and
active, then writes the synthetic rows again.
Seeding overwrites rows by key, so running it on an untouched table changes nothing.
"""
import subprocess
import sys

import boto3

TABLES = ("agl-claims-staging", "agl-claims-production", "agl-tickets-staging", "agl-tickets-production")
ddb = boto3.client("dynamodb", region_name="us-east-1")

for name in TABLES:
    try:
        status = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
    except ddb.exceptions.ResourceNotFoundException:
        sys.exit(f"{name} does not exist. Deploy the data stacks with `make deploy`.")
    if status != "ACTIVE":
        sys.exit(f"{name} is {status}, not ACTIVE. Try again when it is.")
subprocess.run([sys.executable, "scripts/seed.py"], check=True)
