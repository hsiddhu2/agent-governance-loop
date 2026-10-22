import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

from stacks import nag

# Personal data a support or claims tool could return. CloudWatch Logs masks matches
# for anyone without logs:Unmask. Masking is a backstop: tools still should not log it.
MASKED = [
    logs.DataIdentifier.SSN_US,
    logs.DataIdentifier.INDIVIDUALTAXIDENTIFICATIONNUMBER_US,
    logs.DataIdentifier.BANKACCOUNTNUMBER_US,
    logs.DataIdentifier.CREDITCARDNUMBER,
    logs.DataIdentifier.DRIVERSLICENSE_US,
    logs.DataIdentifier.PASSPORTNUMBER_US,
    logs.DataIdentifier.EMAILADDRESS,
    logs.DataIdentifier.PHONENUMBER_US,
    logs.DataIdentifier.NAME,
    logs.DataIdentifier.ADDRESS,
]


def log_group(scope: Construct, id: str, name: str, key: kms.IKey) -> logs.LogGroup:
    """A log group as every part of this pattern needs one: encrypted, masked, bounded."""
    return logs.LogGroup(
        scope, id,
        log_group_name=name,
        encryption_key=key,
        data_protection_policy=logs.DataProtectionPolicy(
            name=f"{id}-mask-personal-data",
            description="Mask personal data in log events",
            identifiers=MASKED,
        ),
        retention=logs.RetentionDays.ONE_MONTH,
        # Sandbox teardown. A production log group is retained for its audit period.
        removal_policy=cdk.RemovalPolicy.DESTROY,
    )


def send_function_logs(fn: Construct, group: logs.ILogGroup) -> None:
    """Point a function CDK created for us at a log group the stack owns.

    Left alone, Lambda writes to a group it creates on first run, with no key, no
    retention, and nothing to remove it with the stack. Referring to the group by
    name also makes CloudFormation create the group before the function.
    """
    # A Function construct wraps its resource. A provider's handler is the resource itself.
    resource = fn.node.default_child or fn
    resource.add_property_override("LoggingConfig.LogGroup", group.log_group_name)


def settle_service_log_group(scope: Construct, id: str, name: str, like: logs.LogGroup) -> Construct:
    """Give a log group that a service creates the same key, masking and retention as `like`.

    Some services create their own log group, named after an id that exists only once
    the service resource does. CloudFormation cannot create that group first, so it is
    not declared as a resource. Each setting is applied to it with a Logs API call when
    the stack deploys, copied from a group this pattern owns, so the two cannot drift
    apart in code. The group outlives the stack and is removed at teardown.
    """
    stack = cdk.Stack.of(scope)
    source = like.node.default_child
    group = Construct(scope, id)
    arn = stack.format_arn(service="logs", resource="log-group", resource_name=name,
                           arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME)
    settings = {
        "Retention": ("putRetentionPolicy", "logs:PutRetentionPolicy",
                      {"logGroupName": name, "retentionInDays": source.retention_in_days}),
        "Key": ("associateKmsKey", "logs:AssociateKmsKey",
                {"logGroupName": name, "kmsKeyId": source.kms_key_id}),
        "Masking": ("putDataProtectionPolicy", "logs:PutDataProtectionPolicy",
                    {"logGroupIdentifier": name,
                     "policyDocument": stack.to_json_string(source.data_protection_policy)}),
    }
    # Associating a key also needs DescribeKey on it, by the caller, through Logs only.
    describe_key = iam.PolicyStatement(
        actions=["kms:DescribeKey"], resources=[source.kms_key_id],
        conditions={"StringEquals": {"kms:ViaService": f"logs.{stack.region}.amazonaws.com"}})
    for setting, (call, action, parameters) in settings.items():
        sdk_call = cr.AwsSdkCall(service="CloudWatchLogs", action=call, parameters=parameters,
                                 physical_resource_id=cr.PhysicalResourceId.of(f"{name}:{setting}"))
        statements = [iam.PolicyStatement(actions=[action], resources=[arn])]
        if setting == "Key":
            statements.append(describe_key)
        cr.AwsCustomResource(
            group, setting,
            on_create=sdk_call,
            on_update=sdk_call,
            policy=cr.AwsCustomResourcePolicy.from_statements(statements),
            # The SDK bundled with the function. Fetching the latest at deploy time
            # would pull code from the internet into a deploy.
            install_latest_aws_sdk=False,
        )
    nag.acknowledge(group, {
        "NIST.800.53.R5-IAMNoInlinePolicy":
            "CDK writes each deploy-time call's permission as an inline policy on its shared "
            "function's role: one Logs action on this one log group.",
    })
    return group
