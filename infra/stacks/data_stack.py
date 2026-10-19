import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from constructs import Construct

from stacks import nag

ENVIRONMENTS = ("staging", "production")


class DataStack(cdk.Stack):
    """One real claims table for one environment, holding synthetic rows.

    Each environment gets its own stack so a deleted table can be rebuilt
    without touching the other one.
    """

    def __init__(self, scope: Construct, id: str, *, env_name: str, **kw):
        super().__init__(scope, id, **kw)
        self.table = ddb.Table(
            self, "Store",
            table_name=f"agl-claims-{env_name}",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            # Left off deliberately: IAM and DynamoDB must both allow the delete,
            # so the only thing standing in the way is the Cedar policy.
            deletion_protection=False,
        )
        nag.acknowledge(self.table, {
            "AwsSolutions-DDB3": "Synthetic rows, rebuilt by `make reset` after each scenario. "
            "A table holding real data should turn on point-in-time recovery.",
        })
