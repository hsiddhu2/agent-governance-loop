import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as _lambda
from constructs import Construct

from stacks import nag
from stacks.logs import log_group as owned_log_group


class ToolsStack(cdk.Stack):
    """The ops tool Lambda, running under a role that can do more than its callers should."""

    def __init__(self, scope: Construct, id: str, logs_key: kms.IKey, data_key: kms.IKey,
                 vpc: ec2.IVpc, security_group: ec2.ISecurityGroup, **kw):
        super().__init__(scope, id, **kw)

        role = iam.Role(
            self, "OpsToolRole",
            role_name="agl-ops-tool-overscoped",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        # Matched by name, not by reference, so a data stack can be replaced on its own.
        claims_tables = self.format_arn(service="dynamodb", resource="table",
                                        resource_name="agl-claims-*")
        log_group = owned_log_group(self, "OpsToolsLogs", "/aws/lambda/agl-ops-tools", logs_key)

        # Customer-managed policies, not inline ones, so each can be reviewed and
        # versioned on its own.
        tool_policy = iam.ManagedPolicy(self, "OpsToolPolicy", statements=[
            iam.PolicyStatement(sid="Describe", actions=["dynamodb:DescribeTable"],
                                resources=[claims_tables]),
            # The over-scope. Nothing in IAM stops this role purging every claim record.
            # Deletion protection, backups and point-in-time recovery guard the table,
            # not its rows. The Cedar policy at the Gateway is the control that stops it.
            iam.PolicyStatement(sid="OverScopedPurge",
                                actions=["dynamodb:Scan", "dynamodb:BatchWriteItem", "dynamodb:DeleteItem"],
                                resources=[claims_tables]),
            # The tables are encrypted with the data key. Usable only through DynamoDB.
            iam.PolicyStatement(sid="DataKeyViaDynamoDB",
                                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                                resources=[data_key.key_arn],
                                conditions={"StringEquals": {
                                    "kms:ViaService": f"dynamodb.{self.region}.amazonaws.com"}}),
            # An owned log group instead of the managed basic-execution policy: the role
            # can write here and nowhere else.
            iam.PolicyStatement(sid="WriteOwnLogs", actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                                resources=[f"{log_group.log_group_arn}:*"]),
        ])
        # ListTables has no resource-level scoping. It sits in its own policy so the
        # acknowledgement below covers this one statement, not every wildcard on the role.
        list_tables = iam.ManagedPolicy(self, "ListTablesManagedPolicy", statements=[
            iam.PolicyStatement(sid="ListTables", actions=["dynamodb:ListTables"], resources=["*"]),
        ])
        # What Lambda needs to attach the function to its subnets. The same actions as the
        # AWS managed VPC access policy, held here so the role carries no managed policy.
        vpc_access = iam.ManagedPolicy(self, "VpcAccessPolicy", statements=[
            iam.PolicyStatement(sid="Eni", resources=["*"], actions=[
                "ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets",
                "ec2:DeleteNetworkInterface", "ec2:AssignPrivateIpAddresses",
                "ec2:UnassignPrivateIpAddresses"]),
        ])

        # Attached from the role side, so the role lists each policy and the function,
        # which depends on the role, is not updated until every policy is in place.
        for policy in (tool_policy, list_tables, vpc_access):
            role.add_managed_policy(policy)

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
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[security_group],
            # Bounds how hard a runaway caller can hit the claims stores.
            reserved_concurrent_executions=5,
        )

        nag.acknowledge(tool_policy, {
            "AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:dynamodb:us-east-1:<AWS::AccountId>:table/agl-claims-*]":
                "Deliberate. Purge on every claims table is the over-scope this pattern "
                "demonstrates. Cedar policy at the Gateway is the control that stops it.",
            "AwsSolutions-IAM5[Resource::<OpsToolsLogsB0DAFE6B.Arn>:*]":
                "Log stream names are assigned by Lambda at run time, inside this one log group.",
        })
        nag.acknowledge(list_tables, {
            "AwsSolutions-IAM5[Resource::*]":
                "dynamodb:ListTables does not support resource-level permissions, and list_env uses it.",
        })
        nag.acknowledge(vpc_access, {
            "AwsSolutions-IAM5[Resource::*]":
                "Lambda creates and removes network interfaces whose ids are not known in advance. "
                "The describe actions do not support resource-level permissions.",
        })
        nag.acknowledge(self.ops_fn, {
            "NIST.800.53.R5-LambdaDLQ":
                "The Gateway invokes the function synchronously. A dead-letter queue only receives "
                "failed asynchronous events, so a failure here goes back to the caller and to the logs.",
        })
