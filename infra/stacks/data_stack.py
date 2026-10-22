import aws_cdk as cdk
from aws_cdk import aws_backup as backup
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_kms as kms
from constructs import Construct

from stacks import nag

ENVIRONMENTS = ("staging", "production")


class DataStack(cdk.Stack):
    """One claims store for one environment, protected as a store of record.

    The table cannot be deleted while deletion protection is on, keeps 35 days of
    point-in-time recovery, is backed up daily, and is encrypted with the data key.
    None of that stops a caller with write access from purging its records, which is
    the gap the Cedar policy at the Gateway closes. Rows are synthetic.
    """

    def __init__(self, scope: Construct, id: str, *, env_name: str, data_key: kms.IKey, **kw):
        super().__init__(scope, id, **kw)
        self.table = ddb.Table(
            self, "Store",
            table_name=f"agl-claims-{env_name}",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            encryption=ddb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=data_key,
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            deletion_protection=True,
            # Teardown turns deletion protection off first (scripts/prepare_destroy.py).
            # A production store of record is retained.
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        vault = backup.BackupVault(
            self, "Vault",
            backup_vault_name=f"agl-claims-{env_name}",
            encryption_key=data_key,
            # The vault can only be removed once it is empty; teardown deletes its
            # recovery points first.
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        plan = backup.BackupPlan(self, "Plan", backup_plan_name=f"agl-claims-{env_name}")
        plan.add_rule(backup.BackupPlanRule(
            rule_name="daily",
            backup_vault=vault,
            schedule_expression=events.Schedule.cron(hour="5", minute="0"),
            delete_after=cdk.Duration.days(35),
        ))
        selection = plan.add_selection(
            "Store", resources=[backup.BackupResource.from_dynamo_db_table(self.table)])
        nag.acknowledge(selection, {
            "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
            "AWSBackupServiceRolePolicyForBackup]":
                "The service role AWS Backup documents for running backups. AWS maintains it as "
                "Backup adds resource types.",
        })
