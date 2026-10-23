import aws_cdk as cdk
from aws_cdk import aws_backup as backup
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_events as events
from aws_cdk import aws_kms as kms
from constructs import Construct

from stacks import nag

ENVIRONMENTS = ("staging", "production")


class DataStack(cdk.Stack):
    """The claims store and the support ticket store for one environment, each
    protected as a store of record.

    Each table cannot be deleted while deletion protection is on, keeps 35 days of
    point-in-time recovery, is backed up daily, and is encrypted with the data key.
    None of that stops a caller with write access from purging its records, which is
    the gap the Cedar policy at the Gateway closes. Rows are synthetic.
    """

    def __init__(self, scope: Construct, id: str, *, env_name: str, data_key: kms.IKey, **kw):
        super().__init__(scope, id, **kw)
        self.table = self._store("Store", f"agl-claims-{env_name}", data_key)
        # Customer messages about claims. They hold whatever a customer typed.
        self.tickets = self._store("Tickets", f"agl-tickets-{env_name}", data_key)

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
        for selection_id, table in (("Store", self.table), ("Tickets", self.tickets)):
            selection = plan.add_selection(
                selection_id, resources=[backup.BackupResource.from_dynamo_db_table(table)])
            nag.acknowledge(selection, {
                "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                "AWSBackupServiceRolePolicyForBackup]":
                    "The service role AWS Backup documents for running backups. AWS maintains it as "
                    "Backup adds resource types.",
            })

    def _store(self, id: str, name: str, data_key: kms.IKey) -> ddb.Table:
        return ddb.Table(
            self, id,
            table_name=name,
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
