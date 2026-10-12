import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from constructs import Construct


class ToolsStack(cdk.Stack):
    """The ops tool Lambda, running under a role that can do more than it should."""

    def __init__(self, scope: Construct, id: str, tables: dict, **kw):
        super().__init__(scope, id, **kw)

        role = iam.Role(
            self, "OpsToolRole",
            role_name="agl-ops-tool-overscoped",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        agl_tables = f"arn:aws:dynamodb:{self.region}:{self.account}:table/agl-*"

        role.add_to_policy(iam.PolicyStatement(
            sid="Reads",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan",
                     "dynamodb:DescribeTable"],
            resources=[agl_tables],
        ))
        # ListTables has no resource-level scoping.
        role.add_to_policy(iam.PolicyStatement(
            sid="ListTables",
            actions=["dynamodb:ListTables"],
            resources=["*"],
        ))
        # The over-scope. Nothing in IAM stops this role deleting an agl-* table.
        role.add_to_policy(iam.PolicyStatement(
            sid="OverScopedDelete",
            actions=["dynamodb:DeleteTable"],
            resources=[agl_tables],
        ))

        self.ops_fn = _lambda.Function(
            self, "OpsTools",
            function_name="agl-ops-tools",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("tools/ops", exclude=["schema.json"]),
            role=role,
            timeout=cdk.Duration.seconds(30),
            environment={"TABLE_PREFIX": "agl-"},
        )
