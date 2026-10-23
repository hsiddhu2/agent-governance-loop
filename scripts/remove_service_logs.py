"""Remove log groups that services created for the pattern, as the last step of `make destroy`.

AgentCore creates a log group per runtime, named after the runtime id. The stacks
configure it but do not own it, so deleting the stacks leaves it behind. Lambda also
created groups for CDK's deploy-time functions before those were pointed at groups
the stacks own. Run this after the stacks are gone, so nothing is left to write.
"""
import boto3

REGION = "us-east-1"
PREFIXES = [
    # The runtime name, which every runtime id and so every group name starts with.
    "/aws/bedrock-agentcore/runtimes/agl_ops_agent-",
    "/aws/bedrock-agentcore/runtimes/agl_support_agent-",
    # Groups Lambda named after the stack. Stack-owned groups are lower case, agl-.
    "/aws/lambda/Agl",
]

logs_client = boto3.client("logs", region_name=REGION)

paginator = logs_client.get_paginator("describe_log_groups")
names = [g["logGroupName"] for prefix in PREFIXES
         for page in paginator.paginate(logGroupNamePrefix=prefix) for g in page["logGroups"]]
for name in names:
    logs_client.delete_log_group(logGroupName=name)
    print(f"{name}: deleted")
if not names:
    print("service-created log groups: none left")
