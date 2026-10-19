import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from constructs import Construct

from stacks import nag


class GatewayStack(cdk.Stack):
    """MCP Gateway with the ops target, its policy engine, and trace delivery."""

    def __init__(self, scope: Construct, id: str, ops_fn: _lambda.IFunction,
                 policy_mode: ac.PolicyEngineMode, **kw):
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
            exception_level=ac.GatewayExceptionLevel.DEBUG,
            policy_engine_configuration=ac.GatewayPolicyEngineConfig(
                policy_engine=self.engine,
                mode=policy_mode,
            ),
        )
        # Sandbox only: remove the user pool with the stack. A production pool holds
        # identities worth keeping, so leave the construct's default (retain) there.
        self.gateway.user_pool.apply_removal_policy(cdk.RemovalPolicy.DESTROY)

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
        log_group = logs.LogGroup(
            self, "GatewayLogs",
            log_group_name="/aws/vendedlogs/bedrock-agentcore/gateway/agl-gateway",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
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
        cdk.CfnOutput(self, "ClientId", value=self.gateway.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "UserPoolId", value=self.gateway.user_pool.user_pool_id)
        cdk.CfnOutput(self, "Scopes", value=",".join(self.gateway.oauth_scopes))
        cdk.CfnOutput(self, "PolicyEngineArn", value=self.engine.policy_engine_arn)
