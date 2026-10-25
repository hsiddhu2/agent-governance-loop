"""The CDK app: every stack of the pattern and the order they depend on each other.

`cdk.json` runs this file. Context values it reads: `expires` (required, the date every
resource is tagged to expire), `policy_mode` (ENFORCE or LOG_ONLY, ENFORCE by default),
`policies_dir` (where the rendered policies are, `policies` by default), `model_id` and
`model_regions` (the agents' model and where it may run), and `nag` (`true` runs the
cdk-nag rule packs).
"""
import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac

from stacks import tags
from stacks.agents_stack import OPS, SUPPORT, AgentsStack
from stacks.audit_stack import AuditStack
from stacks.data_stack import ENVIRONMENTS, DataStack
from stacks.gateway_stack import GatewayStack
from stacks.keys_stack import KeysStack
from stacks.network_stack import NetworkStack
from stacks.policy_stack import PolicyStack, rendered_policies
from stacks.registry_stack import RegistryStack
from stacks.tools_stack import ToolsStack

app = cdk.App()
# Fixed on purpose. This project only runs in us-east-1.
env = cdk.Environment(region="us-east-1")
expires = app.node.try_get_context("expires")
policies_dir = Path(app.node.try_get_context("policies_dir") or "policies")
# ENFORCE unless asked otherwise, so a deploy without the flag is never permissive.
# LOG_ONLY records every decision and applies none of them.
mode_name = app.node.try_get_context("policy_mode") or "ENFORCE"
if mode_name not in ("ENFORCE", "LOG_ONLY"):
    sys.exit(f"policy_mode must be ENFORCE or LOG_ONLY, got {mode_name!r}")
policy_mode = getattr(ac.PolicyEngineMode, mode_name)
# Named here so a library upgrade cannot change the model. The us. inference
# profile keeps requests inside US regions.
model_id = app.node.try_get_context("model_id") or "us.anthropic.claude-sonnet-4-6"
# Where that profile may send a request. IAM must name each one. Read them with
# `aws bedrock get-inference-profile --inference-profile-identifier <model_id>`.
model_regions = (app.node.try_get_context("model_regions") or "us-east-1,us-east-2,us-west-2").split(",")

keys = KeysStack(app, "AglKeys", env=env)
data = [DataStack(app, f"AglData{name.title()}", env_name=name, data_key=keys.data_key, env=env)
        for name in ENVIRONMENTS]
audit = AuditStack(app, "AglAudit", audit_key=keys.audit_key, logs_key=keys.logs_key, env=env)
network = NetworkStack(app, "AglNetwork", logs_key=keys.logs_key, env=env)
tools = ToolsStack(app, "AglTools", logs_key=keys.logs_key, data_key=keys.data_key,
                   vpc=network.vpc, security_group=network.tools_sg, env=env)
gw = GatewayStack(app, "AglGateway", ops_fn=tools.ops_fn, support_fn=tools.support_fn,
                  policy_mode=policy_mode, logs_key=keys.logs_key, env=env)
agents = AgentsStack(app, "AglAgents", gateway=gw.gateway, model_id=model_id,
                     model_regions=model_regions, logs_key=keys.logs_key,
                     ops_credentials=gw.ops_agent_credentials,
                     support_credentials=gw.support_agent_credentials,
                     support_scopes=gw.support_scopes, env=env)
# The policy stack always exists so every synth produces the same set of stacks.
# Its contents come from the .cedar files `make discover` renders from the live
# Gateway; before that it deploys empty.
policy = PolicyStack(app, "AglPolicy", engine=gw.engine, policies_dir=policies_dir,
                     targets=[gw.ops_target, gw.support_target], env=env)
# The catalog. Each agent's record names its runtime, its Gateway principal and what
# its policy templates declare for it.
catalog_tags = {"project": "agl", "env": "sandbox", "expires": expires or ""}
registry = RegistryStack(app, "AglRegistry", gateway_url=gw.gateway.gateway_url, tags=catalog_tags, agents=[
    {"prefix": "Ops", "name": OPS.slug, "display_name": "Claims operations agent",
     "purpose": "Answers operators' questions about claims and claims stores. Reads claim files. "
                "Never purges.",
     "runtime_arn": agents.runtimes[OPS].agent_runtime_arn, "invoke_scope": OPS.invoke_scope,
     "gateway_principal": gw.gateway.user_pool_client.user_pool_client_id, "policy_principal": "ops_agent",
     "model_id": model_id,
     "data_handled": ["claim records", "policyholder statements", "attending physician statements"]},
    {"prefix": "Support", "name": SUPPORT.slug, "display_name": "Customer support agent",
     "purpose": "Reads customer support tickets and drafts replies, looking up the claim a ticket is "
                "about through the minimized claim view.",
     "runtime_arn": agents.runtimes[SUPPORT].agent_runtime_arn, "invoke_scope": SUPPORT.invoke_scope,
     "gateway_principal": gw.support_client.user_pool_client_id, "policy_principal": "support_agent",
     "model_id": model_id,
     "data_handled": ["support tickets, which can carry identifiers customers paste", "claim summaries"]},
], env=env)
if not rendered_policies(policies_dir):
    print(f"AglPolicy has no policies: no rendered .cedar files under {policies_dir}. "
          "Run `make discover`.", file=sys.stderr)

for s in [keys, audit, network, *data, tools, gw, policy, agents, registry]:
    tags.apply(s, expires)

# `make check` and every deploy synth with -c nag=true. Two rule packs review every
# resource: AWS Solutions, and NIST SP 800-53 Rev 5, a published catalog of security
# and privacy controls. Any finding without a written acknowledgement fails the synth.
if app.node.try_get_context("nag") == "true":
    from cdk_nag import AwsSolutionsChecks, NIST80053R5Checks

    cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app), NIST80053R5Checks(app))

app.synth()
