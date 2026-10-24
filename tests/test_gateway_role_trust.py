"""The Gateway's service role may be assumed only for this account's own Gateway.

Allow statements in a trust policy are combined, so one statement without conditions
would make the conditions on any other statement meaningless.
"""
import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from aws_cdk.assertions import Template

from stacks.gateway_stack import GatewayStack
from stacks.keys_stack import KeysStack
from stacks.network_stack import NetworkStack
from stacks.tools_stack import ToolsStack


def gateway_role_trust() -> list[dict]:
    app = cdk.App()
    env = cdk.Environment(region="us-east-1")
    keys = KeysStack(app, "Keys", env=env)
    network = NetworkStack(app, "Network", logs_key=keys.logs_key, env=env)
    tools = ToolsStack(app, "Tools", logs_key=keys.logs_key, data_key=keys.data_key,
                       vpc=network.vpc, security_group=network.tools_sg, env=env)
    gw = GatewayStack(app, "Gateway", ops_fn=tools.ops_fn, support_fn=tools.support_fn,
                      policy_mode=ac.PolicyEngineMode.ENFORCE, logs_key=keys.logs_key, env=env)
    roles = Template.from_stack(gw).find_resources("AWS::IAM::Role")
    (role,) = [r for k, r in roles.items() if k.startswith("GatewayServiceRole")]
    return role["Properties"]["AssumeRolePolicyDocument"]["Statement"]


def test_every_trust_statement_is_limited_to_this_account_and_gateway():
    statements = gateway_role_trust()
    assert len(statements) == 1
    (only,) = statements
    assert only["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert set(only["Condition"]) == {"StringEquals", "ArnLike"}
    assert "aws:SourceAccount" in only["Condition"]["StringEquals"]
    # The ARN is a token join. Its last part names the Gateway.
    assert only["Condition"]["ArnLike"]["aws:SourceArn"]["Fn::Join"][1][-1].endswith(":gateway/agl-gateway*")
