"""Write synthetic claim rows into both claims stores. No field holds personal data."""
import boto3

ddb = boto3.resource("dynamodb", region_name="us-east-1")
STATUSES = ("open", "in_review", "closed")
ROWS = [{"pk": f"claim#{i}", "policy_number": f"TEST-POL-{i:05d}",
         "status": STATUSES[i % len(STATUSES)], "amount": 1000 + 250 * i}
        for i in range(50)]

for env in ("staging", "production"):
    table = ddb.Table(f"agl-claims-{env}")
    with table.batch_writer() as batch:
        for row in ROWS:
            batch.put_item(Item={**row, "env": env})
    print(f"agl-claims-{env}: wrote {len(ROWS)} test claims")
