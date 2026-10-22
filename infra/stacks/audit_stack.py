import aws_cdk as cdk
from aws_cdk import aws_cloudtrail as cloudtrail
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct

from stacks import nag
from stacks.keys_stack import TRAIL_NAME
from stacks.logs import log_group

# Every tools/list and tools/call that reaches a Gateway in this account and Region.
# Management events are left to the trail the account already has.
GATEWAY_DATA_EVENTS = [{
    "Name": "Gateway tool calls",
    "FieldSelectors": [
        {"Field": "eventCategory", "Equals": ["Data"]},
        {"Field": "resources.type", "Equals": ["AWS::BedrockAgentCore::Gateway"]},
    ],
}]


class AuditStack(cdk.Stack):
    """A CloudTrail record of every call to the Gateway, kept apart from the decision spans.

    Gateway calls are data events, which no trail records unless asked. Each event names
    the tool, the caller's token claims and the response, with arguments and results
    redacted by the service. Log file validation lets anyone check the files were not
    changed after delivery.
    """

    def __init__(self, scope: Construct, id: str, *, audit_key: kms.IKey, logs_key: kms.IKey, **kw):
        super().__init__(scope, id, **kw)

        bucket = s3.Bucket(
            self, "TrailBucket",
            bucket_name=f"agl-audit-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=audit_key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            enforce_ssl=True,
            versioned=True,
            # Sandbox retention, matching the log groups. A production trail keeps its
            # files for the audit period, under Object Lock.
            lifecycle_rules=[s3.LifecycleRule(expiration=cdk.Duration.days(30),
                                              noncurrent_version_expiration=cdk.Duration.days(1))],
            # Sandbox teardown. `make destroy` stops the trail and empties the bucket first.
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        nag.acknowledge(bucket, {
            "AwsSolutions-S1":
                "Only CloudTrail writes here. Reads of the trail files are themselves "
                "recorded by the account trail. A production trail delivers to a central "
                "log archive account, which keeps its own access logs.",
            "NIST.800.53.R5-S3BucketLoggingEnabled":
                "Same reason as AwsSolutions-S1.",
            "NIST.800.53.R5-S3BucketReplicationEnabled":
                "Sandbox. A production trail delivers to a central log archive account.",
        })

        # The construct lets CloudTrail write here for any trail. Only this one may.
        trail_arn = self.format_arn(service="cloudtrail", resource="trail", resource_name=TRAIL_NAME)
        bucket.add_to_resource_policy(iam.PolicyStatement(
            effect=iam.Effect.DENY,
            principals=[iam.ServicePrincipal("cloudtrail.amazonaws.com")],
            actions=["s3:GetBucketAcl", "s3:PutObject"],
            resources=[bucket.bucket_arn, bucket.arn_for_objects("*")],
            conditions={"StringNotEquals": {"aws:SourceArn": trail_arn}},
        ))

        trail = cloudtrail.Trail(
            self, "GatewayTrail",
            trail_name=TRAIL_NAME,
            bucket=bucket,
            encryption_key=audit_key,
            enable_file_validation=True,
            send_to_cloud_watch_logs=True,
            cloud_watch_log_group=log_group(self, "TrailLogs", "/aws/cloudtrail/agl-gateway", logs_key),
            is_multi_region_trail=False,
            include_global_service_events=False,
        )
        # The construct offers basic selectors only, which cannot name a Gateway.
        # A trail takes one kind of selector or the other.
        cfn = trail.node.default_child
        cfn.add_property_override("AdvancedEventSelectors", GATEWAY_DATA_EVENTS)
        cfn.add_property_deletion_override("EventSelectors")
        nag.acknowledge(trail, {
            "NIST.800.53.R5-IAMNoInlinePolicy":
                "The construct writes the CloudWatch Logs delivery grant as an inline "
                "default policy on its role: two Logs actions on this one log group.",
        })
