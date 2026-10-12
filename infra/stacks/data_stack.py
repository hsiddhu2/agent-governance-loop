import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from constructs import Construct


class DataStack(cdk.Stack):
    """Two real tables holding synthetic rows."""

    def __init__(self, scope: Construct, id: str, **kw):
        super().__init__(scope, id, **kw)
        self.tables: dict[str, ddb.Table] = {}
        for name in ("staging", "production"):
            self.tables[name] = ddb.Table(
                self, f"Store{name.title()}",
                table_name=f"agl-{name}",
                partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
                billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                removal_policy=cdk.RemovalPolicy.DESTROY,
                # Left off deliberately: IAM and DynamoDB must both allow the delete,
                # so the only thing standing in the way is the Cedar policy.
                deletion_protection=False,
            )
