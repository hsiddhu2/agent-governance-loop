"""Write synthetic claim records into both claims stores.

Each claim carries a policyholder statement and a health statement, the kind of
documents a life claim file holds. Every value is fictional: see synthetic.py.
Staging also gets one probe record per kind of field, which the guardrail matrix reads.
"""
import boto3

from synthetic import claims, probes

ddb = boto3.resource("dynamodb", region_name="us-east-1")

for env in ("staging", "production"):
    table = ddb.Table(f"agl-claims-{env}")
    rows = claims() + (probes() if env == "staging" else [])
    with table.batch_writer() as batch:
        for row in rows:
            batch.put_item(Item={**row, "env": env})
    print(f"agl-claims-{env}: wrote {len(rows)} synthetic records")
