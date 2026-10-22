"""The tool function must not be updated before its role's policies are attached.

Lambda checks the role when the function joins its subnets. A policy that attaches
itself to the role (the policy's Roles property) gives CloudFormation no reason to
wait for it, so the function can be updated first and the deploy fails.
"""
import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.keys_stack import KeysStack
from stacks.network_stack import NetworkStack
from stacks.tools_stack import ToolsStack


def tools_template() -> dict:
    app = cdk.App()
    env = cdk.Environment(region="us-east-1")
    keys = KeysStack(app, "Keys", env=env)
    network = NetworkStack(app, "Network", logs_key=keys.logs_key, env=env)
    tools = ToolsStack(app, "Tools", logs_key=keys.logs_key, data_key=keys.data_key,
                       vpc=network.vpc, security_group=network.tools_sg, env=env)
    return Template.from_stack(tools).to_json()["Resources"]


def of_type(resources: dict, kind: str) -> dict:
    return {k: r for k, r in resources.items() if r["Type"] == kind}


def test_policies_attach_from_the_role():
    resources = tools_template()
    policies = of_type(resources, "AWS::IAM::ManagedPolicy")
    assert policies
    assert not any("Roles" in p["Properties"] for p in policies.values())
    [role] = of_type(resources, "AWS::IAM::Role").values()
    attached = {ref["Ref"] for ref in role["Properties"]["ManagedPolicyArns"] if "Ref" in ref}
    assert attached == set(policies)


def test_function_waits_for_its_role():
    resources = tools_template()
    [role_id] = of_type(resources, "AWS::IAM::Role")
    [fn] = of_type(resources, "AWS::Lambda::Function").values()
    assert fn["Properties"]["Role"] == {"Fn::GetAtt": [role_id, "Arn"]}
    assert fn["Properties"]["VpcConfig"]["SubnetIds"]
