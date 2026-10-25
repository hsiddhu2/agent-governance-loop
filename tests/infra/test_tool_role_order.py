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
    roles = of_type(resources, "AWS::IAM::Role").values()
    attached = {ref["Ref"] for role in roles
                for ref in role["Properties"]["ManagedPolicyArns"] if "Ref" in ref}
    assert attached == set(policies)


def test_each_function_waits_for_its_own_role():
    resources = tools_template()
    roles = set(of_type(resources, "AWS::IAM::Role"))
    functions = of_type(resources, "AWS::Lambda::Function").values()
    used = [fn["Properties"]["Role"]["Fn::GetAtt"][0] for fn in functions]
    assert sorted(used) == sorted(roles)
    assert all(fn["Properties"]["VpcConfig"]["SubnetIds"] for fn in functions)


def test_support_role_cannot_write():
    resources = tools_template()
    [support] = [k for k, r in of_type(resources, "AWS::IAM::Role").items()
                 if r["Properties"].get("RoleName") == "agl-support-tool"]
    refs = {ref["Ref"] for ref in resources[support]["Properties"]["ManagedPolicyArns"] if "Ref" in ref}
    actions = {a for ref in refs for st in resources[ref]["Properties"]["PolicyDocument"]["Statement"]
               for a in ([st["Action"]] if isinstance(st["Action"], str) else st["Action"])}
    assert not {a for a in actions if a.startswith("dynamodb:")} - {"dynamodb:GetItem"}
