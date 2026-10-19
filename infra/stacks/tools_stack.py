import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from constructs import Construct

from stacks import nag


class ToolsStack(cdk.Stack):
    """The ops tool Lambda, running under a role that can do more than it should."""

    def __init__(self, scope: Construct, id: str, **kw):
        super().__init__(scope, id, **kw)

        role = iam.Role(
            self, "OpsToolRole",
            role_name="agl-ops-tool-overscoped",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        # Matched by name, not by reference, so the data stack can be torn down and
        # rebuilt on its own after a scenario deletes a table.
        agl_tables = f"arn:aws:dynamodb:{self.region}:{self.account}:table/agl-*"

        role.add_to_policy(iam.PolicyStatement(
            sid="Describe",
            actions=["dynamodb:DescribeTable"],
            resources=[agl_tables],
        ))
        # ListTables has no resource-level scoping. It sits in its own policy so the
        # acknowledgement below covers this one statement, not every wildcard on the role.
        list_tables = iam.Policy(self, "ListTablesPolicy", roles=[role], statements=[
            iam.PolicyStatement(sid="ListTables", actions=["dynamodb:ListTables"], resources=["*"]),
        ])
        # The over-scope. Nothing in IAM stops this role deleting an agl-* table.
        role.add_to_policy(iam.PolicyStatement(
            sid="OverScopedDelete",
            actions=["dynamodb:DeleteTable"],
            resources=[agl_tables],
        ))

        # An owned log group instead of the managed basic-execution policy: the role
        # can write here and nowhere else, and the group goes away with the stack.
        log_group = logs.LogGroup(
            self, "OpsToolsLogs",
            log_group_name="/aws/lambda/agl-ops-tools",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.ops_fn = _lambda.Function(
            self, "OpsTools",
            function_name="agl-ops-tools",
            runtime=_lambda.Runtime.PYTHON_3_14,
            handler="handler.handler",
            code=_lambda.Code.from_asset("tools/ops", exclude=["schema.json"]),
            role=role,
            log_group=log_group,
            timeout=cdk.Duration.seconds(30),
            environment={"TABLE_PREFIX": "agl-claims-"},
        )
        log_group.grant_write(role)

        nag.acknowledge(role, {
            "AwsSolutions-IAM5[Resource::arn:aws:dynamodb:us-east-1:<AWS::AccountId>:table/agl-*]":
                "Deliberate. Delete on every agl-* table is the over-scope this pattern "
                "demonstrates. Cedar policy at the Gateway is the control that stops it.",
        })
        nag.acknowledge(list_tables, {
            "AwsSolutions-IAM5[Resource::*]":
                "dynamodb:ListTables does not support resource-level permissions, and list_env uses it.",
        })
