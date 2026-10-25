import json
import re
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from constructs import Construct

from stacks.policy_stack import POLICY_DIRS

# The policy templates are read, not the rendered policies, so this stack is the same
# before and after `make discover`.
TEMPLATES = Path("policies")
TOOL_SCHEMAS = (Path("tools/ops/schema.json"), Path("tools/support/schema.json"))
SERVICE_ROLE = "aws-service-role/agent-registry.amazonaws.com/AWSServiceRoleForAgentRegistry"

EFFECT = re.compile(r"^\s*(permit|forbid|suppressOutput)\s*\(", re.MULTILINE)
PRINCIPAL = re.compile(r"\{\{PRINCIPAL:(\w+)\}\}")
TOOL = re.compile(r"\{\{TOOL:(\w+)\}\}")


def declared_policy(agent: str, templates: Path = TEMPLATES) -> dict:
    """What the policy templates say about one agent's tools.

    A permit names its principal. A forbid or a screen with no named principal applies
    to every caller. Each list is sorted so the record does not change between synths.
    """
    permitted, forbidden, screens = set(), set(), {}
    for tmpl in sorted((t for d in POLICY_DIRS for t in Path(templates, d).glob("*.cedar.tmpl")),
                       key=lambda t: t.name):
        text = tmpl.read_text()
        effect = EFFECT.search(text)
        if not effect:
            continue
        principals = set(PRINCIPAL.findall(text))
        if principals and agent not in principals:
            continue
        tools = TOOL.findall(text)
        if effect.group(1) == "permit":
            permitted.update(tools)
        elif effect.group(1) == "forbid":
            forbidden.update(tools)
        else:
            screens[tmpl.name.removesuffix(".cedar.tmpl")] = tools
    return {
        "permitted_tools": sorted(permitted),
        "forbidden_tools": sorted(forbidden),
        # A screen matters to an agent only on a tool it may call.
        "screens": {name: tools for name, tools in sorted(screens.items())
                    if set(tools) & permitted},
    }


def tool_definitions(schemas=TOOL_SCHEMAS) -> list[dict]:
    """Every tool the Gateway's targets declare, as MCP tool definitions."""
    return [tool for path in schemas for tool in json.loads(path.read_text())]


class RegistryStack(cdk.Stack):
    """The catalog: one registry recording the Gateway's tools and each agent.

    A record says what exists, what it is for and how it is reached. It grants nothing:
    an agent that finds a tool here still calls it through the Gateway, where policy
    decides. Records are created as drafts. A reviewer approves each one before search
    returns it (`make approve-catalog`).
    """

    def __init__(self, scope: Construct, id: str, gateway_url: str, agents: list[dict],
                 tags: dict[str, str], **kw):
        super().__init__(scope, id, **kw)

        # Its own key, in this stack, because the key policy names the service's role,
        # and IAM rejects a key policy naming a role that does not exist yet. The role is
        # created before this stack is deployed (`make deploy-registry`).
        self.key = kms.Key(
            self, "RegistryKey",
            alias="alias/agl-registry",
            description="Encrypts the pattern's agent and tool catalog",
            enable_key_rotation=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            pending_window=cdk.Duration.days(7),
        )
        # The registry encrypts and decrypts record content through its service-linked
        # role, only for registries in this account.
        self.key.add_to_resource_policy(iam.PolicyStatement(
            principals=[iam.ArnPrincipal(f"arn:{self.partition}:iam::{self.account}:role/{SERVICE_ROLE}")],
            actions=["kms:Decrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlaintext",
                     "kms:Encrypt", "kms:ReEncryptFrom", "kms:ReEncryptTo"],
            resources=["*"],
            conditions={"StringLike": {"kms:EncryptionContext:aws:agent-registry:registry-arn":
                                       f"arn:{self.partition}:agent-registry:{self.region}:{self.account}:registry/*"}},
        ))

        # CloudFormation types with no CDK construct yet, declared directly. CDK's tag
        # pass does not reach them, so their tags are set here.
        cfn_tags = [{"Key": k, "Value": v} for k, v in sorted(tags.items())]
        registry = cdk.CfnResource(self, "Registry", type="AWS::AgentRegistry::Registry", properties={
            "Name": "agl-registry",
            "Description": "Agents and tools of the claims governance pattern, "
                           "each approved before it is listed",
            # Search signs requests with AWS credentials, so IAM decides who may search.
            "AuthorizerType": "AWS_IAM",
            # No auto-approval rule: every record waits for a reviewer.
            "ApprovalConfiguration": {"AutoApprovalRules": []},
            "EncryptionConfiguration": {"KmsKeyArn": self.key.key_arn},
            "Tags": cfn_tags,
        })
        registry.node.add_dependency(self.key)
        # The template schema bundled with aws-cdk-lib predates this property. The live
        # resource schema in CloudFormation lists it, and a deploy validates against that.
        cdk.Validations.of(registry).acknowledge(cdk.Acknowledgment(
            id="CloudFormation-Validate::F3002",
            reason="EncryptionConfiguration is in the live AWS::AgentRegistry::Registry schema "
                   "but not yet in the schema bundled with aws-cdk-lib."))
        registry_id = registry.get_att("RegistryId").to_string()

        tools = tool_definitions()
        # The Gateway is one MCP server. Its record lists every tool its targets declare,
        # the purge included: a catalog shows what exists, and policy decides who may call it.
        # The Gateway exposes each tool under its target's name, so a caller reads the exact
        # names from tools/list.
        server = {
            "name": "com.example.agl/claims-gateway",
            "description": "Claims operations and support tools, each call decided by Cedar policy",
            "version": "1.0.0",
            "remotes": [{"type": "streamable-http", "url": gateway_url}],
        }
        record_type = "AWS::AgentRegistry::RegistryRecord"
        self.records = [cdk.CfnResource(self, "GatewayRecord", type=record_type, properties={
            "RegistryId": registry_id,
            "Name": "agl-claims-gateway",
            "DisplayName": "Claims Gateway",
            "Description": "MCP Gateway for claims operations and customer support. Tools: "
                           + "; ".join(f"{t['name']}: {t['description']}" for t in tools),
            "RecordType": "MCP",
            "RecordVersion": "1.0.0",
            "Descriptors": {"McpServer": {
                "Data": json.dumps(server),
                "AdditionalData": {"Tools": {"Data": json.dumps({"tools": tools})}},
            }},
            "Tags": cfn_tags,
        })]

        # Each agent is a custom record. The agents serve plain HTTP on AgentCore Runtime,
        # not A2A, so an agent card would describe a protocol they do not speak.
        for agent in agents:
            record = cdk.CfnResource(self, f"{agent['prefix']}AgentRecord", type=record_type, properties={
                "RegistryId": registry_id,
                "Name": agent["name"],
                "DisplayName": agent["display_name"],
                "Description": agent["purpose"],
                "RecordType": "CUSTOM",
                "RecordVersion": "1.0.0",
                "Descriptors": {"Custom": {"Data": json.dumps({
                    "kind": "agent",
                    "purpose": agent["purpose"],
                    "runtime": {"arn": agent["runtime_arn"], "protocol": "HTTP",
                                "inbound": f"JWT, scope {agent['invoke_scope']}"},
                    "gateway": {"url": gateway_url, "principal": agent["gateway_principal"]},
                    "model": agent["model_id"],
                    "data_handled": agent["data_handled"],
                    # As written in the policy templates. What is live is read from the
                    # policy engine, not from here.
                    "declared_policy": declared_policy(agent["policy_principal"]),
                })}},
                "Tags": cfn_tags,
            })
            self.records.append(record)

        cdk.CfnOutput(self, "RegistryId", value=registry_id)
        cdk.CfnOutput(self, "RegistryArn", value=registry.get_att("RegistryArn").to_string())
