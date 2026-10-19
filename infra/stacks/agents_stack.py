from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from constructs import Construct

from stacks import nag

# Built by scripts/package_agent.sh: agent code plus Linux arm64 dependencies.
OPS_AGENT_BUILD = "build/ops_agent"
OPS_RUNTIME_NAME = "agl_ops_agent"


class AgentsStack(cdk.Stack):
    """The Ops Agent on AgentCore Runtime, calling tools through the Gateway."""

    def __init__(self, scope: Construct, id: str, gateway: ac.Gateway, model_id: str,
                 model_regions: list[str], **kw):
        super().__init__(scope, id, **kw)

        if not Path(OPS_AGENT_BUILD, "main.py").exists():
            raise RuntimeError(f"{OPS_AGENT_BUILD} is missing. Run `make package`.")

        artifact = ac.AgentRuntimeArtifact.from_code_asset(
            path=OPS_AGENT_BUILD,
            runtime=ac.AgentCoreRuntime.PYTHON_3_12,
            entrypoint=["opentelemetry-instrument", "main.py"],
        )

        log_group = logs.LogGroup(
            self, "OpsAgentLogs",
            log_group_name="/aws/vendedlogs/bedrock-agentcore/agl-ops-agent",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.ops_runtime = ac.Runtime(
            self, "OpsAgent",
            runtime_name=OPS_RUNTIME_NAME,
            agent_runtime_artifact=artifact,
            tracing_enabled=True,
            logging_configs=[ac.LoggingConfig(
                log_type=ac.LogType.APPLICATION_LOGS,
                destination=ac.LoggingDestination.cloud_watch_logs(log_group),
            )],
            environment_variables={
                "MODEL_ID": model_id,
                "GW_URL": gateway.gateway_url,
                "GW_TOKEN_URL": gateway.token_endpoint_url,
                "GW_CLIENT_ID": gateway.user_pool_client.user_pool_client_id,
                "GW_USER_POOL_ID": gateway.user_pool.user_pool_id,
                "GW_SCOPES": " ".join(gateway.oauth_scopes),
            },
        )

        # The agent's own permissions sit in their own policy. The construct's default
        # policy carries acknowledged wildcards (below), so a statement added there could
        # hide behind them. Here, any new wildcard fails `make check`.
        #
        # The pinned model only, and only through its inference profile. The profile
        # routes each request to one of its destination Regions, so the model is
        # allowed in each of those, on condition the call came through the profile.
        invoke = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        profile_arn = self.format_arn(service="bedrock", resource="inference-profile",
                                      resource_name=model_id)
        foundation_model = model_id.split(".", 1)[1]
        agent_policy = iam.Policy(self, "OpsAgentPolicy", roles=[self.ops_runtime.role], statements=[
            iam.PolicyStatement(actions=invoke, resources=[profile_arn]),
            iam.PolicyStatement(
                actions=invoke,
                resources=[f"arn:{self.partition}:bedrock:{region}::foundation-model/{foundation_model}"
                           for region in model_regions],
                conditions={"StringEquals": {"bedrock:InferenceProfileArn": profile_arn}},
            ),
            # The agent fetches its own client secret to get a Gateway token.
            iam.PolicyStatement(
                actions=["cognito-idp:DescribeUserPoolClient"],
                resources=[gateway.user_pool.user_pool_arn],
            ),
            # New agents write their spans to their own log group rather than aws/spans.
            # AgentCore needs this to let X-Ray deliver into that group. Scoped by the
            # runtime name, which prefixes the runtime id; referencing the id itself
            # would make the role depend on the runtime that depends on the role.
            iam.PolicyStatement(
                actions=["logs:PutResourcePolicy"],
                resources=[self.format_arn(
                    service="logs", resource="log-group",
                    resource_name=f"/aws/bedrock-agentcore/runtimes/{OPS_RUNTIME_NAME}-*",
                    arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME)],
            ),
        ])
        # Permissions in place before the runtime starts. Only the runtime resource
        # waits: the construct also holds the role this policy attaches to.
        self.ops_runtime.node.default_child.node.add_dependency(agent_policy)
        nag.acknowledge(agent_policy, {
            "AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:logs:us-east-1:<AWS::AccountId>:log-group:"
            f"/aws/bedrock-agentcore/runtimes/{OPS_RUNTIME_NAME}-*]":
                "Scoped to this runtime by name prefix. The runtime id does not exist until deploy, "
                "and referencing it would create a dependency cycle.",
        })

        asset_bucket = "arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-us-east-1"
        runtime_logs = "arn:<AWS::Partition>:logs:us-east-1:<AWS::AccountId>:log-group:"
        nag.acknowledge(self.ops_runtime, {
            **{f"AwsSolutions-IAM5[Action::s3:{a}]":
               "Added by the Runtime construct to read the agent's code bundle from the CDK asset bucket."
               for a in ("GetObject*", "GetBucket*", "List*")},
            f"AwsSolutions-IAM5[Resource::{asset_bucket}/*]":
                "The agent's code bundle lives at a content-hashed key in the CDK asset bucket.",
            "AwsSolutions-IAM5[Resource::*]":
                "X-Ray trace writes and cloudwatch:PutMetricData do not support resource-level "
                "permissions. Added by the Runtime construct for tracing.",
            f"AwsSolutions-IAM5[Resource::{runtime_logs}*]":
                "logs:DescribeLogGroups needs the account-level log-group resource.",
            f"AwsSolutions-IAM5[Resource::{runtime_logs}/aws/bedrock-agentcore/runtimes/*]":
                "Runtime log group names include an id assigned at deploy time.",
            f"AwsSolutions-IAM5[Resource::{runtime_logs}/aws/bedrock-agentcore/runtimes/*:log-stream:*]":
                "Runtime log stream names are assigned at run time.",
            "AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:bedrock-agentcore:us-east-1:"
            "<AWS::AccountId>:workload-identity-directory/default/workload-identity/*]":
                "Added by the Runtime construct. The workload identity is created with the runtime.",
        })

        cdk.CfnOutput(self, "OpsRuntimeArn", value=self.ops_runtime.agent_runtime_arn)
