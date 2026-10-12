import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from constructs import Construct


class GatewayStack(cdk.Stack):
    """MCP Gateway with the ops target, its policy engine, and trace delivery."""

    def __init__(self, scope: Construct, id: str, ops_fn: _lambda.IFunction, **kw):
        super().__init__(scope, id, **kw)

        # The engine is attached at creation in ENFORCE mode. Policies are added
        # later by AglPolicy, once tool names are known. Until then, default deny.
        self.engine = ac.PolicyEngine(
            self, "Engine",
            policy_engine_name="agl_engine",
            description="Cedar authorization for agl-gateway",
        )

        # No authorizer passed, so the construct creates a Cognito M2M client.
        # That client's sub is the principal Cedar evaluates.
        self.gateway = ac.Gateway(
            self, "Gateway",
            gateway_name="agl-gateway",
            exception_level=ac.GatewayExceptionLevel.DEBUG,
            policy_engine_configuration=ac.GatewayPolicyEngineConfig(
                policy_engine=self.engine,
                mode=ac.PolicyEngineMode.ENFORCE,
            ),
        )

        # The target name becomes part of every tool name the Gateway exposes.
        self.ops_target = self.gateway.add_lambda_target(
            "OpsTarget",
            gateway_target_name="ops",
            lambda_function=ops_fn,
            tool_schema=ac.ToolSchema.from_local_asset("tools/ops/schema.json"),
        )

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

        cdk.CfnOutput(self, "GatewayUrl", value=self.gateway.gateway_url)
        cdk.CfnOutput(self, "GatewayArn", value=self.gateway.gateway_arn)
        cdk.CfnOutput(self, "TokenEndpoint", value=self.gateway.token_endpoint_url)
        cdk.CfnOutput(self, "ClientId", value=self.gateway.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "UserPoolId", value=self.gateway.user_pool.user_pool_id)
        cdk.CfnOutput(self, "Scopes", value=",".join(self.gateway.oauth_scopes))
        cdk.CfnOutput(self, "PolicyEngineArn", value=self.engine.policy_engine_arn)
