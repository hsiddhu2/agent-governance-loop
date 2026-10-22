import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from constructs import Construct


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
