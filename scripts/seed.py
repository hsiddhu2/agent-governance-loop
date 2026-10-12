"""Write synthetic rows into both data stores."""
import boto3

ddb = boto3.resource("dynamodb", region_name="us-east-1")
ROWS = [{"pk": f"customer#{i}", "name": f"Synthetic Customer {i}", "plan": "pro"}
        for i in range(50)]

for env in ("staging", "production"):
    table = ddb.Table(f"agl-{env}")
    with table.batch_writer() as batch:
        for row in ROWS:
            batch.put_item(Item={**row, "env": env})
    print(f"seeded agl-{env}: {len(ROWS)} rows")
