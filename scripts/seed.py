"""Write synthetic claim records and support tickets into both environments.

Each claim carries a policyholder statement and a health statement, the kind of
documents a life claim file holds. Each ticket is a customer's message about one
claim. Every value is fictional: see synthetic.py.
Staging also gets one probe record per kind of field, which scripts/screen_matrix.py reads.
"""
import boto3

from synthetic import claims, probes, tickets

ddb = boto3.resource("dynamodb", region_name="us-east-1")

for env in ("staging", "production"):
    stores = {
        f"agl-claims-{env}": claims() + (probes() if env == "staging" else []),
        f"agl-tickets-{env}": tickets(),
    }
    for name, rows in stores.items():
        with ddb.Table(name).batch_writer() as batch:
            for row in rows:
                batch.put_item(Item={**row, "env": env})
        print(f"{name}: wrote {len(rows)} synthetic records")
