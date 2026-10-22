import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_kms as kms
from constructs import Construct

from stacks import nag
from stacks.logs import log_group as owned_log_group
from stacks.logs import send_function_logs


class NetworkStack(cdk.Stack):
    """A private network for the tool functions, with no route to the internet.

    The tools only call DynamoDB, which they reach through a gateway endpoint. No NAT,
    no internet gateway. Flow logs record every connection attempt.
    """

    def __init__(self, scope: Construct, id: str, logs_key: kms.IKey, **kw):
        super().__init__(scope, id, **kw)

        self.vpc = ec2.Vpc(
            self, "Vpc",
            vpc_name="agl-tools",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[ec2.SubnetConfiguration(
                name="tools", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24)],
            # The default security group allows all traffic between its members. Strip it.
            restrict_default_security_group=True,
        )
        self.vpc.add_gateway_endpoint("DynamoDB", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB)
        # The function CDK adds to strip the default security group's rules.
        provider = self.node.find_child("Custom::VpcRestrictDefaultSGCustomResourceProvider")
        deploy_logs = owned_log_group(self, "DeployLogs", "/aws/lambda/agl-deploy-network", logs_key)
        send_function_logs(provider.node.find_child("Handler"), deploy_logs)

        flow_logs = owned_log_group(self, "FlowLogs", "/aws/vpc/agl-tools", logs_key)
        flow_log = self.vpc.add_flow_log(
            "FlowLog", destination=ec2.FlowLogDestination.to_cloud_watch_logs(flow_logs))
        nag.acknowledge(flow_log, {
            "NIST.800.53.R5-IAMNoInlinePolicy":
                "The flow log construct writes its delivery role's grant as an inline default policy, "
                "scoped to this one log group.",
        })

        # Tools may open HTTPS connections and nothing else. The subnets' only route
        # out is the DynamoDB endpoint, so HTTPS reaches DynamoDB alone. Naming the
        # DynamoDB prefix list here would need a context lookup that records the
        # account in the repo.
        self.tools_sg = ec2.SecurityGroup(
            self, "ToolsSg", vpc=self.vpc, allow_all_outbound=False,
            description="Tool functions: outbound HTTPS only",
        )
        self.tools_sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443),
                                      "HTTPS, routed only to the DynamoDB endpoint")
