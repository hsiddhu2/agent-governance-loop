import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

from stacks import nag
from stacks.logs import log_group as owned_log_group
from stacks.logs import send_function_logs


class GatewayStack(cdk.Stack):
    """MCP Gateway with the ops target, its policy engine, and trace delivery."""

    def __init__(self, scope: Construct, id: str, ops_fn: _lambda.IFunction,
                 policy_mode: ac.PolicyEngineMode, logs_key: kms.IKey, **kw):
        super().__init__(scope, id, **kw)

        # Policies are added later by AglPolicy, once tool names are known. The
        # Gateway hides tools that policy denies from tools/list, so discovery runs
        # with the engine in LOG_ONLY and enforcement is switched on afterwards.
        self.engine = ac.PolicyEngine(
            self, "Engine",
            policy_engine_name="agl_engine",
            description="Decides which tool calls on the ops gateway may run",
        )

        # No authorizer passed, so the construct creates a Cognito M2M client.
        # That client's sub is the principal Cedar evaluates.
        self.gateway = ac.Gateway(
            self, "Gateway",
            gateway_name="agl-gateway",
            # No exception_level: callers get no internal error detail. The decision
            # record, including the determining policy, is in the Gateway logs and spans.
            policy_engine_configuration=ac.GatewayPolicyEngineConfig(
                policy_engine=self.engine,
                mode=policy_mode,
            ),
        )
        # Sandbox only: remove the user pool with the stack. A production pool holds
        # identities worth keeping, so leave the construct's default (retain) there.
        self.gateway.user_pool.apply_removal_policy(cdk.RemovalPolicy.DESTROY)

        # The client's logical id is set here so the client can be replaced, which issues
        # a new id and a new secret, by changing this one value.
        self.gateway.user_pool_client.node.default_child.override_logical_id("OpsAgentClientV2")

        # The ops agent's Gateway credential. The agent never sees its client secret.
        # AgentCore Identity keeps it in the token vault and hands the agent a Gateway
        # token through its workload identity. The provider lives in this stack, beside
        # the client, so the secret passes by reference inside one template and never
        # becomes a stack output.
        self.ops_agent_credentials = ac.OAuth2CredentialProvider.using_cognito(
            self, "OpsAgentGatewayCredentials",
            o_auth2_credential_provider_name="agl-ops-agent-gateway",
            client_id=self.gateway.user_pool_client.user_pool_client_id,
            client_secret=self.gateway.user_pool_client.user_pool_client_secret,
            issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{self.gateway.user_pool.user_pool_id}",
            # Required by the service for the Cognito vendor, though the client-credentials
            # flow uses only the token endpoint.
            authorization_endpoint=f"{self.gateway.user_pool_domain.base_url()}/oauth2/authorize",
            token_endpoint=self.gateway.token_endpoint_url,
        )

        # The target name becomes part of every tool name the Gateway exposes.
        self.ops_target = self.gateway.add_lambda_target(
            "OpsTarget",
            gateway_target_name="ops",
            lambda_function=ops_fn,
            tool_schema=ac.ToolSchema.from_local_asset("tools/ops/schema.json"),
        )

        nag.acknowledge(self.gateway.user_pool, {
            **{f"AwsSolutions-COG{n}": "The pool has no human users. Its only client uses the "
               "client-credentials flow, so passwords, MFA and sign-in threat protection do not apply."
               for n in (1, 2, 8)},
        })
        asset_bucket = "arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-us-east-1"
        # The Lambda ARN reaches this stack as a weak reference, so the finding id
        # carries the reference text. A rename of the tools stack output changes it.
        ops_fn_versions = ('{"Fn::GetStackOutput":{"StackName":"AglTools","Region":"us-east-1",'
                           '"OutputName":"PublishOutputFnGetAttOpsToolsE3B3FFF4ArnA8F67AAB"}}:*')
        nag.acknowledge(self.gateway, {
            **{f"AwsSolutions-IAM5[Action::s3:{a}]": "Added by the Gateway construct to read the "
               "tool schema from the CDK asset bucket." for a in ("GetObject*", "GetBucket*", "List*")},
            f"AwsSolutions-IAM5[Resource::{asset_bucket}/*]":
                "The tool schema lives at a content-hashed key in the CDK asset bucket.",
            f"AwsSolutions-IAM5[Resource::{ops_fn_versions}]":
                "Invoke on the tool function and its versions, added by the Gateway target construct.",
            "NIST.800.53.R5-IAMNoInlinePolicy":
                "The Gateway construct writes its service role's grants as an inline default policy, "
                "including the custom resource that reads the generated client secret at deploy time.",
        })
        # CDK's shared function behind that custom resource. It runs only during deployment,
        # to hand the client secret to AgentCore Identity without writing it into a template.
        # The credential provider above read the secret, which created it.
        reader = self.node.find_child("AWS" + cr.AwsCustomResource.PROVIDER_FUNCTION_UUID.replace("-", ""))
        deploy_logs = owned_log_group(self, "DeployLogs", "/aws/lambda/agl-deploy-gateway", logs_key)
        send_function_logs(reader, deploy_logs)
        deploy_only = ("CDK's deploy-time custom resource function. It runs only while CloudFormation "
                       "deploys this stack, is invoked synchronously by CloudFormation, and calls one "
                       "Cognito API.")
        nag.acknowledge(reader, {
            "AwsSolutions-IAM4[Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
            "AWSLambdaBasicExecutionRole]": deploy_only,
            "NIST.800.53.R5-LambdaDLQ": deploy_only,
            "NIST.800.53.R5-LambdaConcurrency": deploy_only,
            "NIST.800.53.R5-LambdaInsideVPC": deploy_only,
        })

        # Policy decisions are emitted as Gateway spans. They only reach the
        # aws/spans log group if the Gateway itself delivers traces to X-Ray.
        trace_source = logs.CfnDeliverySource(
            self, "GatewayTraceSource",
            name="agl-gateway-traces",
            log_type="TRACES",
            resource_arn=self.gateway.gateway_arn,
        )
        trace_dest = logs.CfnDeliveryDestination(
            self, "GatewayTraceDestination",
            name="agl-gateway-traces-xray",
            delivery_destination_type="XRAY",
        )
        delivery = logs.CfnDelivery(
            self, "GatewayTraceDelivery",
            delivery_source_name=trace_source.name,
            delivery_destination_arn=trace_dest.attr_arn,
        )
        delivery.add_resource_dependency(trace_source)

        # Request and response records for every Gateway call. They carry the same
        # trace_id and span_id as the spans above, so the two can be joined.
        log_group = owned_log_group(self, "GatewayLogs",
                                    "/aws/vendedlogs/bedrock-agentcore/gateway/agl-gateway", logs_key)
        log_source = logs.CfnDeliverySource(
            self, "GatewayLogSource",
            name="agl-gateway-logs",
            log_type="APPLICATION_LOGS",
            resource_arn=self.gateway.gateway_arn,
        )
        log_dest = logs.CfnDeliveryDestination(
            self, "GatewayLogDestination",
            name="agl-gateway-logs-cwl",
            destination_resource_arn=log_group.log_group_arn,
        )
        log_delivery = logs.CfnDelivery(
            self, "GatewayLogDelivery",
            delivery_source_name=log_source.name,
            delivery_destination_arn=log_dest.attr_arn,
        )
        log_delivery.add_resource_dependency(log_source)

        cdk.CfnOutput(self, "GatewayLogGroup", value=log_group.log_group_name)
        cdk.CfnOutput(self, "GatewayUrl", value=self.gateway.gateway_url)
        cdk.CfnOutput(self, "GatewayArn", value=self.gateway.gateway_arn)
        cdk.CfnOutput(self, "TokenEndpoint", value=self.gateway.token_endpoint_url)
        # The construct's client belongs to the ops agent. Its id is the ops agent's
        # Cedar principal. Scripts use it to call the Gateway with the agent's own
        # credential, without the model.
        cdk.CfnOutput(self, "ClientId", value=self.gateway.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "OpsAgentClientId", value=self.gateway.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "UserPoolId", value=self.gateway.user_pool.user_pool_id)
        cdk.CfnOutput(self, "Scopes", value=",".join(self.gateway.oauth_scopes))
        cdk.CfnOutput(self, "PolicyEngineArn", value=self.engine.policy_engine_arn)
