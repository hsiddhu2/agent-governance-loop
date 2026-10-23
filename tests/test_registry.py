"""The catalog: what each record says, and the reviewer that approves it."""
import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from approve_catalog import check_agent, check_gateway
from stacks.registry_stack import RegistryStack, declared_policy, tool_definitions

URL = "https://gw.example/mcp"


def test_ops_agent_declared_policy_comes_from_the_templates():
    p = declared_policy("ops_agent")
    assert p["permitted_tools"] == ["get_claim", "get_claim_record", "get_claims_store", "list_env"]
    assert p["forbidden_tools"] == ["purge_claims"]
    assert set(p["screens"]) == {"ops_screen_contact_details", "ops_screen_financial",
                                 "ops_screen_government_ids", "ops_screen_health_ids"}


def test_support_agent_gets_only_the_screens_on_its_own_tools():
    p = declared_policy("support_agent")
    assert p["permitted_tools"] == ["get_claim", "get_ticket"]
    # The forbid names no principal, so it applies to every agent.
    assert p["forbidden_tools"] == ["purge_claims"]
    assert set(p["screens"]) == {"support_screen_financial", "support_screen_government_ids"}


def test_the_catalog_lists_every_declared_tool_the_purge_included():
    names = [t["name"] for t in tool_definitions()]
    assert "purge_claims" in names and "get_ticket" in names
    assert len(names) == len(set(names))


def synth() -> Template:
    app = cdk.App()
    stack = RegistryStack(app, "R", gateway_url=URL, tags={"project": "agl"}, agents=[{
        "prefix": "Ops", "name": "agl-ops-agent", "display_name": "Ops", "purpose": "p",
        "runtime_arn": "arn:aws:bedrock-agentcore:us-east-1:acct:runtime/r-1",
        "invoke_scope": "agl-ops-agent/invoke", "gateway_principal": "client1",
        "policy_principal": "ops_agent", "model_id": "m", "data_handled": ["claims"]}])
    return Template.from_stack(stack)


def test_records_wait_for_a_reviewer_and_use_the_catalog_key():
    t = synth()
    t.has_resource_properties("AWS::AgentRegistry::Registry", {
        "ApprovalConfiguration": {"AutoApprovalRules": []},
        "AuthorizerType": "AWS_IAM",
        "EncryptionConfiguration": {"KmsKeyArn": Match.any_value()},
        "Tags": [{"Key": "project", "Value": "agl"}],
    })
    t.resource_count_is("AWS::AgentRegistry::RegistryRecord", 2)


def test_the_mcp_record_points_at_the_gateway():
    t = synth()
    record = t.find_resources("AWS::AgentRegistry::RegistryRecord", {"Properties": {"RecordType": "MCP"}})
    mcp = next(iter(record.values()))["Properties"]["Descriptors"]["McpServer"]
    server = json.loads(mcp["Data"])
    assert server["remotes"] == [{"type": "streamable-http", "url": URL}]
    # The MCP server schema caps the description at 100 characters.
    assert len(server["description"]) <= 100


GATEWAY = {"gatewayUrl": URL, "status": "READY",
           "authorizerConfiguration": {"customJWTAuthorizer": {"allowedClients": ["client1"]}}}


def mcp_record(url: str) -> dict:
    return {"descriptors": {"mcpServer": {"data": json.dumps({"remotes": [{"url": url}]})}}}


def test_reviewer_approves_a_gateway_record_that_matches():
    assert check_gateway(mcp_record(URL), GATEWAY) == []


def test_reviewer_rejects_a_gateway_record_for_another_gateway():
    assert check_gateway(mcp_record("https://other/mcp"), GATEWAY)


class Control:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self, runtimes: dict):
        self.runtimes = runtimes

    def get_agent_runtime(self, agentRuntimeId):
        if agentRuntimeId not in self.runtimes:
            raise self.exceptions.ResourceNotFoundException()
        return {"status": self.runtimes[agentRuntimeId]}


def agent_record(principal: str = "client1") -> dict:
    data = {"kind": "agent", "runtime": {"arn": "arn:x:runtime/r-1"},
            "gateway": {"url": URL, "principal": principal}}
    return {"descriptors": {"custom": {"data": json.dumps(data)}}}


def test_reviewer_approves_an_agent_record_that_matches():
    assert check_agent(agent_record(), GATEWAY, Control({"r-1": "READY"})) == []


def test_reviewer_rejects_an_agent_whose_runtime_is_gone():
    assert check_agent(agent_record(), GATEWAY, Control({})) == ["runtime r-1 does not exist"]


def test_reviewer_rejects_an_agent_the_gateway_does_not_accept():
    problems = check_agent(agent_record("stranger"), GATEWAY, Control({"r-1": "READY"}))
    assert problems == ["its Gateway principal is not a client the Gateway accepts"]
