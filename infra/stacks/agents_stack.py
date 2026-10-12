from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from constructs import Construct

# Built by scripts/package_agent.sh: agent code plus Linux arm64 dependencies.
OPS_AGENT_BUILD = "build/ops_agent"


class AgentsStack(cdk.Stack):
    """The Ops Agent on AgentCore Runtime, calling tools through the Gateway."""

    def __init__(self, scope: Construct, id: str, gateway: ac.Gateway, **kw):
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
            runtime_name="agl_ops_agent",
            agent_runtime_artifact=artifact,
            tracing_enabled=True,
            logging_configs=[ac.LoggingConfig(
                log_type=ac.LogType.APPLICATION_LOGS,
                destination=ac.LoggingDestination.cloud_watch_logs(log_group),
            )],
            environment_variables={
                "GW_URL": gateway.gateway_url,
                "GW_TOKEN_URL": gateway.token_endpoint_url,
                "GW_CLIENT_ID": gateway.user_pool_client.user_pool_client_id,
                "GW_USER_POOL_ID": gateway.user_pool.user_pool_id,
                "GW_SCOPES": " ".join(gateway.oauth_scopes),
            },
        )

        self.ops_runtime.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=["*"],
        ))
        # The agent fetches its own client secret to get a Gateway token.
        self.ops_runtime.add_to_role_policy(iam.PolicyStatement(
            actions=["cognito-idp:DescribeUserPoolClient"],
            resources=[gateway.user_pool.user_pool_arn],
        ))

        cdk.CfnOutput(self, "OpsRuntimeArn", value=self.ops_runtime.agent_runtime_arn)
