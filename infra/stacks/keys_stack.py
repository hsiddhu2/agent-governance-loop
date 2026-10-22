import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from constructs import Construct

# Fixed so the audit key's policy can name the trail before the trail exists.
TRAIL_NAME = "agl-gateway-tool-calls"


class KeysStack(cdk.Stack):
    """Customer-managed KMS keys, one per kind of data, each with yearly rotation.

    Separate keys keep the blast radius of a key policy small: access to log data
    does not imply access to stored records.
    """

    def __init__(self, scope: Construct, id: str, **kw):
        super().__init__(scope, id, **kw)

        self.logs_key = kms.Key(
            self, "LogsKey",
            alias="alias/agl-logs",
            description="Encrypts the pattern's CloudWatch log groups",
            enable_key_rotation=True,
            # Sandbox teardown. A production key is retained.
            removal_policy=cdk.RemovalPolicy.DESTROY,
            pending_window=cdk.Duration.days(7),
        )
        # CloudWatch Logs encrypts with this key on the log group's behalf. Limited to
        # this account's log groups by the encryption context Logs sends.
        self.logs_key.add_to_resource_policy(iam.PolicyStatement(
            principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
            actions=["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*",
                     "kms:Describe*"],
            resources=["*"],
            conditions={"ArnLike": {"kms:EncryptionContext:aws:logs:arn":
                                    f"arn:{self.partition}:logs:{self.region}:{self.account}:log-group:*"}},
        ))

        self.data_key = kms.Key(
            self, "DataKey",
            alias="alias/agl-data",
            description="Encrypts the pattern's data stores",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            pending_window=cdk.Duration.days(7),
        )

        self.audit_key = kms.Key(
            self, "AuditKey",
            alias="alias/agl-audit",
            description="Encrypts the Gateway's tool-call trail",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            pending_window=cdk.Duration.days(7),
        )
        # CloudTrail encrypts each log file it delivers, and only for the one trail named
        # here. Readers decrypt through IAM: the key policy lets this account grant it.
        trail = f"arn:{self.partition}:cloudtrail:{self.region}:{self.account}:trail/{TRAIL_NAME}"
        cloudtrail = iam.ServicePrincipal("cloudtrail.amazonaws.com")
        self.audit_key.add_to_resource_policy(iam.PolicyStatement(
            principals=[cloudtrail],
            actions=["kms:GenerateDataKey*"],
            resources=["*"],
            conditions={
                "StringEquals": {"aws:SourceArn": trail},
                "StringLike": {"kms:EncryptionContext:aws:cloudtrail:arn": trail},
            },
        ))
        self.audit_key.add_to_resource_policy(iam.PolicyStatement(
            principals=[cloudtrail],
            actions=["kms:DescribeKey"],
            resources=["*"],
            conditions={"StringEquals": {"aws:SourceArn": trail}},
        ))
