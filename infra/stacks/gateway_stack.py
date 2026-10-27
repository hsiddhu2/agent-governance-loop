import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

from stacks import nag
from stacks.logs import log_group as owned_log_group
from stacks.logs import send_function_logs


class GatewayStack(cdk.Stack):
    """MCP Gateway with the ops and support targets, its policy engine, and trace delivery."""

    def __init__(self, scope: Construct, id: str, ops_fn: _lambda.IFunction, support_fn: _lambda.IFunction,
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
        # The construct's service role trusts the AgentCore service in two statements: one
        # with no condition, and one limited to this account and this Gateway's name. Allow
        # statements are combined, so the unconditioned one makes the limit meaningless.
        # Keep only the limited statement. Remove this once the construct drops the other
        # (https://github.com/aws/aws-cdk/issues/38780).
        self.gateway.role.node.default_child.add_property_override(
            "AssumeRolePolicyDocument.Statement", [{
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {"aws:SourceArn": f"arn:{self.partition}:bedrock-agentcore:{self.region}:"
                                                 f"{self.account}:gateway/{self.gateway.gateway_name}*"},
                },
            }])

        # Sandbox only: remove the user pool with the stack. A production pool holds
        # identities worth keeping, so leave the construct's default (retain) there.
        self.gateway.user_pool.apply_removal_policy(cdk.RemovalPolicy.DESTROY)

        # The client's logical id is set here so the client can be replaced, which issues
        # a new id and a new secret, by changing this one value.
        self.gateway.user_pool_client.node.default_child.override_logical_id("OpsAgentClientV2")

        # The ops agent's Gateway credential. The agent code never handles its client secret.
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

        # The support agent's own Gateway client in the same pool, so it is its own Cedar
        # principal. It may ask for the read scope only.
        read_scope = next(s for s in self.gateway.oauth_scopes if s.endswith("/read"))
        support_client = self.gateway.user_pool.add_client(
            "SupportAgentClient",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(client_credentials=True),
                scopes=[cognito.OAuthScope.custom(read_scope)],
            ),
        )
        self.support_client = support_client
        self.support_scopes = [read_scope]
        # The construct allows only its own client. The Gateway accepts a token only from
        # a client on this list, so the support client is added beside it. Changing the
        # authorizer updates the Gateway in place: its ARN, which every policy names, stays.
        self.gateway.node.default_child.add_property_override(
            "AuthorizerConfiguration.CustomJWTAuthorizer.AllowedClients",
            [self.gateway.user_pool_client.user_pool_client_id, support_client.user_pool_client_id])
        self.support_agent_credentials = ac.OAuth2CredentialProvider.using_cognito(
            self, "SupportAgentGatewayCredentials",
            o_auth2_credential_provider_name="agl-support-agent-gateway",
            client_id=support_client.user_pool_client_id,
            client_secret=support_client.user_pool_client_secret,
            issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{self.gateway.user_pool.user_pool_id}",
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
        self.support_target = self.gateway.add_lambda_target(
            "SupportTarget",
            gateway_target_name="support",
            lambda_function=support_fn,
            tool_schema=ac.ToolSchema.from_local_asset("tools/support/schema.json"),
        )

        # Guardrails in policy: per the AgentCore guide (Guardrails in policies), the engine
        # calls Bedrock Guardrails with forward access session credentials derived from the
        # Gateway's role, so the grant goes on that role. It has not been tested without it.
        # The Service Authorization Reference lists no resource types and no condition keys
        # for bedrock:InvokeGuardrailChecks, so it cannot be scoped below "*".
        # The AgentCore guide's example scopes it to a guardrail ARN, so the two AWS pages disagree.
        # The checks are defined inline in each policy: there is no guardrail resource to name.
        guardrail_checks = iam.ManagedPolicy(self, "GuardrailChecksPolicy", statements=[
            iam.PolicyStatement(sid="InvokeGuardrailChecks", actions=["bedrock:InvokeGuardrailChecks"],
                                resources=["*"]),
        ])
        self.gateway.role.add_managed_policy(guardrail_checks)
        nag.acknowledge(guardrail_checks, {
            "AwsSolutions-IAM5[Resource::*]":
                "bedrock:InvokeGuardrailChecks has no resource types and no condition keys in the "
                "Service Authorization Reference. Checks are defined inline in each policy, so there "
                "is no guardrail to name.",
        })

        nag.acknowledge(self.gateway.user_pool, {
            **{f"AwsSolutions-COG{n}": "The pool has no human users. Its only client uses the "
               "client-credentials flow, so passwords, MFA and sign-in threat protection do not apply."
               for n in (1, 2, 8)},
        })
        asset_bucket = "arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-us-east-1"
        # The Lambda ARNs reach this stack as weak references, so the finding ids
        # carry the reference text. A rename of a tools stack output changes them.
        fn_versions = [('{"Fn::GetStackOutput":{"StackName":"AglTools","Region":"us-east-1",'
                        f'"OutputName":"{output}"}}}}:*')
                       for output in ("PublishOutputFnGetAttOpsToolsE3B3FFF4ArnA8F67AAB",
                                      "PublishOutputFnGetAttSupportTools1D2E42C8Arn286F4EB0")]
        nag.acknowledge(self.gateway, {
            **{f"AwsSolutions-IAM5[Action::s3:{a}]": "Added by the Gateway construct to read the "
               "tool schema from the CDK asset bucket." for a in ("GetObject*", "GetBucket*", "List*")},
            f"AwsSolutions-IAM5[Resource::{asset_bucket}/*]":
                "The tool schema lives at a content-hashed key in the CDK asset bucket.",
            **{f"AwsSolutions-IAM5[Resource::{versions}]":
               "Invoke on the tool function and its versions, added by the Gateway target construct."
               for versions in fn_versions},
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
                       "deploys this stack, is invoked asynchronously by CloudFormation, which waits for its "
                       "answer, and calls one Cognito API.")
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
        # The support agent's Gateway client and the scope it may ask for. Its id is the
        # support agent's Cedar principal.
        cdk.CfnOutput(self, "SupportAgentClientId", value=support_client.user_pool_client_id)
        cdk.CfnOutput(self, "SupportScopes", value=",".join(self.support_scopes))
        cdk.CfnOutput(self, "UserPoolId", value=self.gateway.user_pool.user_pool_id)
        cdk.CfnOutput(self, "Scopes", value=",".join(self.gateway.oauth_scopes))
        cdk.CfnOutput(self, "PolicyEngineArn", value=self.engine.policy_engine_arn)
