"""The Gateway trail records Gateway data events only, signs its files, and takes files from itself only."""
import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.audit_stack import AuditStack
from stacks.keys_stack import TRAIL_NAME, KeysStack


def audit_resources() -> dict:
    app = cdk.App()
    env = cdk.Environment(region="us-east-1")
    keys = KeysStack(app, "Keys", env=env)
    audit = AuditStack(app, "Audit", audit_key=keys.audit_key, logs_key=keys.logs_key, env=env)
    return Template.from_stack(audit).to_json()["Resources"]


def one(resources: dict, kind: str) -> dict:
    [found] = [r["Properties"] for r in resources.values() if r["Type"] == kind]
    return found


def test_trail_selects_gateway_data_events_only():
    trail = one(audit_resources(), "AWS::CloudTrail::Trail")
    assert "EventSelectors" not in trail
    [selector] = trail["AdvancedEventSelectors"]
    fields = {f["Field"]: f["Equals"] for f in selector["FieldSelectors"]}
    assert fields == {"eventCategory": ["Data"], "resources.type": ["AWS::BedrockAgentCore::Gateway"]}


def test_trail_signs_and_encrypts_its_files():
    trail = one(audit_resources(), "AWS::CloudTrail::Trail")
    assert trail["TrailName"] == TRAIL_NAME
    assert trail["EnableLogFileValidation"] is True
    assert trail["KMSKeyId"]
    assert trail["CloudWatchLogsLogGroupArn"]


def test_bucket_refuses_other_trails():
    statements = one(audit_resources(), "AWS::S3::BucketPolicy")["PolicyDocument"]["Statement"]
    denies = [s for s in statements if s["Effect"] == "Deny"
              and s["Principal"] == {"Service": "cloudtrail.amazonaws.com"}]
    assert len(denies) == 1
    assert set(denies[0]["Action"]) == {"s3:GetBucketAcl", "s3:PutObject"}
    assert "aws:SourceArn" in denies[0]["Condition"]["StringNotEquals"]
