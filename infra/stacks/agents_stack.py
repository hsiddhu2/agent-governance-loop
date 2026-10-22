from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import custom_resources as cr
from constructs import Construct

from stacks import nag
from stacks.logs import log_group as owned_log_group
from stacks.logs import send_function_logs, settle_service_log_group

# Built by scripts/package_agent.sh: agent code plus Linux arm64 dependencies.
OPS_AGENT_BUILD = "build/ops_agent"
OPS_RUNTIME_NAME = "agl_ops_agent"


class AgentsStack(cdk.Stack):
    """The Ops Agent on AgentCore Runtime, calling tools through the Gateway."""

    def __init__(self, scope: Construct, id: str, gateway: ac.Gateway, model_id: str,
                 model_regions: list[str], logs_key: kms.IKey,
                 credentials: ac.OAuth2CredentialProvider, **kw):
        super().__init__(scope, id, **kw)

        if not Path(OPS_AGENT_BUILD, "main.py").exists():
            raise RuntimeError(f"{OPS_AGENT_BUILD} is missing. Run `make package`.")

        artifact = ac.AgentRuntimeArtifact.from_code_asset(
            path=OPS_AGENT_BUILD,
            runtime=ac.AgentCoreRuntime.PYTHON_3_12,
            entrypoint=["opentelemetry-instrument", "main.py"],
        )

        log_group = owned_log_group(self, "OpsAgentLogs",
                                    "/aws/vendedlogs/bedrock-agentcore/agl-ops-agent", logs_key)

        # Who may call the agent. A separate pool from the Gateway's, so a caller's token
        # is accepted by the Runtime and by nothing behind it. Its one client is the ops
        # console: the service a team uses to send requests to the agent. The Runtime
        # validates the console's token, and AgentCore Identity issues the agent's
        # workload token from it.
        operators = cognito.UserPool(
            self, "Operators",
            user_pool_name="agl-operators",
            self_sign_up_enabled=False,
            # Sandbox teardown. A production pool is retained.
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        invoke_scope = cognito.ResourceServerScope(scope_name="invoke",
                                                   scope_description="Call the ops agent")
        agent_api = operators.add_resource_server(
            "OpsAgentApi", identifier="agl-ops-agent", scopes=[invoke_scope])
        domain = operators.add_domain("Domain", cognito_domain=cognito.CognitoDomainOptions(
            domain_prefix=f"agl-operators-{self.node.addr[-8:]}"))
        console = operators.add_client(
            "OpsConsole",
            user_pool_client_name="ops-console",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.resource_server(agent_api, invoke_scope)],
            ),
            # Short-lived. The console asks for a new token per request.
            access_token_validity=cdk.Duration.minutes(15),
        )
        nag.acknowledge(operators, {
            f"AwsSolutions-COG{n}": "The pool has no human users. Its only client is the ops console, "
               "a service using the client-credentials flow, so passwords, MFA and sign-in threat "
               "protection do not apply."
            for n in (1, 2, 8)
        })

        self.ops_runtime = ac.Runtime(
            self, "OpsAgent",
            runtime_name=OPS_RUNTIME_NAME,
            agent_runtime_artifact=artifact,
            tracing_enabled=True,
            authorizer_configuration=ac.RuntimeAuthorizerConfiguration.using_cognito(
                operators, [console], allowed_scopes=["agl-ops-agent/invoke"]),
            logging_configs=[ac.LoggingConfig(
                log_type=ac.LogType.APPLICATION_LOGS,
                destination=ac.LoggingDestination.cloud_watch_logs(log_group),
            )],
            environment_variables={
                "MODEL_ID": model_id,
                "GW_URL": gateway.gateway_url,
                "GW_CREDENTIAL_PROVIDER": credentials.o_auth2_credential_provider_name,
                "GW_SCOPES": " ".join(gateway.oauth_scopes),
            },
        )

        # AgentCore creates a log group for the runtime when it creates the runtime, and
        # writes the runtime's own logs and the agent's spans to it. It gets the same key,
        # masking and retention as the agent's log group.
        settle_service_log_group(
            self, "RuntimeLogs",
            f"/aws/bedrock-agentcore/runtimes/{self.ops_runtime.agent_runtime_id}-DEFAULT",
            like=log_group)
        # CDK's shared function behind those calls. It runs only during deployment.
        settler = self.node.find_child("AWS" + cr.AwsCustomResource.PROVIDER_FUNCTION_UUID.replace("-", ""))
        deploy_logs = owned_log_group(self, "DeployLogs", "/aws/lambda/agl-deploy-agents", logs_key)
        send_function_logs(settler, deploy_logs)
        deploy_only = ("CDK's deploy-time custom resource function. It runs only while CloudFormation "
                       "deploys this stack, is invoked synchronously by CloudFormation, and calls three "
                       "CloudWatch Logs APIs on one log group.")
        nag.acknowledge(settler, {
            "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
            "AWSLambdaBasicExecutionRole]": deploy_only,
            "NIST.800.53.R5-LambdaDLQ": deploy_only,
            "NIST.800.53.R5-LambdaConcurrency": deploy_only,
            "NIST.800.53.R5-LambdaInsideVPC": deploy_only,
        })

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
        agent_policy = iam.ManagedPolicy(
            self, "OpsAgentManagedPolicy", roles=[self.ops_runtime.role], statements=[
            iam.PolicyStatement(actions=invoke, resources=[profile_arn]),
            iam.PolicyStatement(
                actions=invoke,
                resources=[f"arn:{self.partition}:bedrock:{region}::foundation-model/{foundation_model}"
                           for region in model_regions],
                conditions={"StringEquals": {"bedrock:InferenceProfileArn": profile_arn}},
            ),
            # Fetch a Gateway token from the vault: this provider, through this agent's
            # workload identity. The workload identity is named after the runtime id, which
            # starts with the runtime name. Written out rather than taken from grant_use(),
            # which would grant read on every identity secret in the account.
            iam.PolicyStatement(
                actions=["bedrock-agentcore:GetResourceOauth2Token"],
                resources=[credentials.credential_provider_arn,
                           self.format_arn(service="bedrock-agentcore", resource="token-vault",
                                           resource_name="default"),
                           self.format_arn(service="bedrock-agentcore", resource="token-vault",
                                           resource_name="default/oauth2credentialprovider"),
                           self.format_arn(service="bedrock-agentcore",
                                           resource="workload-identity-directory",
                                           resource_name="default"),
                           self.format_arn(service="bedrock-agentcore",
                                           resource="workload-identity-directory",
                                           resource_name=f"default/workload-identity/{OPS_RUNTIME_NAME}-*")],
            ),
            # The token request reads the provider's client secret as the caller. This one
            # secret only: AgentCore Identity names it after the provider, and Secrets Manager
            # appends a suffix. CloudFormation does not return its ARN. Only secrets the
            # identity service owns match.
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[self.format_arn(
                    service="secretsmanager", resource="secret",
                    resource_name="bedrock-agentcore-identity!default/oauth2/"
                                  f"{credentials.o_auth2_credential_provider_name}*",
                    arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME)],
                conditions={"StringEquals": {
                    "aws:ResourceTag/aws:secretsmanager:owningService": "bedrock-agentcore-identity"}},
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
            "AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:bedrock-agentcore:us-east-1:<AWS::AccountId>:"
            f"workload-identity-directory/default/workload-identity/{OPS_RUNTIME_NAME}-*]":
                "The runtime's workload identity is named after the runtime id, which does not exist "
                "until deploy. Scoped to this runtime by name prefix.",
            "AwsSolutions-IAM5[Resource::arn:<AWS::Partition>:secretsmanager:us-east-1:<AWS::AccountId>:"
            "secret:bedrock-agentcore-identity!default/oauth2/agl-ops-agent-gateway*]":
                "The provider's own secret. Secrets Manager adds a random suffix to its name, and "
                "CloudFormation does not return the ARN. Limited to secrets the identity service owns.",
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
            "NIST.800.53.R5-IAMNoInlinePolicy":
                "The Runtime construct writes its execution role's grants as an inline default policy. "
                "This agent's own permissions are in a separate managed policy.",
        })

        cdk.CfnOutput(self, "OpsRuntimeArn", value=self.ops_runtime.agent_runtime_arn)
        # The console's id and where it gets tokens. Never its secret.
        cdk.CfnOutput(self, "OperatorPoolId", value=operators.user_pool_id)
        cdk.CfnOutput(self, "OpsConsoleClientId", value=console.user_pool_client_id)
        cdk.CfnOutput(self, "OperatorTokenEndpoint", value=f"{domain.base_url()}/oauth2/token")
        cdk.CfnOutput(self, "OperatorScope", value="agl-ops-agent/invoke")
