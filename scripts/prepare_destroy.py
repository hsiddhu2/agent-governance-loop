"""Make the claims stores removable, as the first step of `make destroy`.

The stores are protected the way stores of record are: deletion protection on, and a
backup vault that CloudFormation can delete only once it is empty. Teardown therefore
has to undo that on purpose. This turns deletion protection off and empties the
vaults. It also stops the Gateway trail and empties its bucket, so no file lands
between the two deletes. Nothing else is touched. Run it only to remove the pattern.
"""
import sys
import time

import boto3

REGION = "us-east-1"
TABLES = ("agl-claims-staging", "agl-claims-production")
TRAIL = "agl-gateway-tool-calls"
WAIT_SECONDS = 600
ddb = boto3.client("dynamodb", region_name=REGION)
bk = boto3.client("backup", region_name=REGION)
ct = boto3.client("cloudtrail", region_name=REGION)
s3 = boto3.resource("s3", region_name=REGION)


def wait_for(check, what: str) -> None:
    give_up_at = time.time() + WAIT_SECONDS
    while not check():
        if time.time() > give_up_at:
            sys.exit(f"gave up waiting for {what}")
        time.sleep(10)


def unprotect(name: str) -> None:
    try:
        ddb.update_table(TableName=name, DeletionProtectionEnabled=False)
    except ddb.exceptions.ResourceNotFoundException:
        print(f"{name}: not found, nothing to do")
        return

    def done() -> bool:
        t = ddb.describe_table(TableName=name)["Table"]
        return t["TableStatus"] == "ACTIVE" and not t.get("DeletionProtectionEnabled", False)

    # The update applies asynchronously. CloudFormation must not try the delete before it lands.
    wait_for(done, f"{name} to drop deletion protection")
    print(f"{name}: deletion protection off")


def empty_vault(name: str) -> None:
    # Each data stack names its vault after its table.
    def points() -> list[str]:
        pages = bk.get_paginator("list_recovery_points_by_backup_vault").paginate(BackupVaultName=name)
        return [p["RecoveryPointArn"] for page in pages for p in page["RecoveryPoints"]]

    try:
        found = points()
    except bk.exceptions.ResourceNotFoundException:
        print(f"{name} vault: not found, nothing to do")
        return
    # A backup job can add a point while this runs, and deletes complete asynchronously.
    # Keep going until the vault lists nothing.
    deleted = 0
    give_up_at = time.time() + WAIT_SECONDS
    while found:
        if time.time() > give_up_at:
            sys.exit(f"{name} vault: {len(found)} recovery point(s) left after {WAIT_SECONDS}s")
        for arn in found:
            try:
                bk.delete_recovery_point(BackupVaultName=name, RecoveryPointArn=arn)
                deleted += 1
            except bk.exceptions.InvalidRequestException:
                pass  # Still being created or already being deleted. Seen again next pass.
        time.sleep(10)
        found = points()
    print(f"{name} vault: empty ({deleted} recovery point(s) deleted)")


def empty_trail_bucket() -> None:
    try:
        ct.stop_logging(Name=TRAIL)
    except ct.exceptions.TrailNotFoundException:
        print(f"{TRAIL}: not found, nothing to do")
        return
    account = boto3.client("sts").get_caller_identity()["Account"]
    bucket = s3.Bucket(f"agl-audit-{account}-{REGION}")
    # Versioned, so every version and delete marker goes, or the bucket stays non-empty.
    deleted = sum(len(r.get("Deleted", [])) for r in bucket.object_versions.delete())
    print(f"{TRAIL}: logging stopped, {bucket.name} empty ({deleted} version(s) deleted)")


empty_trail_bucket()
for table in TABLES:
    unprotect(table)
    empty_vault(table)
