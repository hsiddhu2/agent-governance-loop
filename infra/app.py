import sys
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac

from stacks import tags
from stacks.agents_stack import AgentsStack
from stacks.data_stack import ENVIRONMENTS, DataStack
from stacks.gateway_stack import GatewayStack
from stacks.policy_stack import PolicyStack, rendered_policies
from stacks.tools_stack import ToolsStack

app = cdk.App()
# Fixed on purpose. This project only runs in us-east-1.
env = cdk.Environment(region="us-east-1")
expires = app.node.try_get_context("expires")
cedar_dir = Path(app.node.try_get_context("cedar_dir") or "policies/cedar")
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

data = [DataStack(app, f"AglData{name.title()}", env_name=name, env=env) for name in ENVIRONMENTS]
tools = ToolsStack(app, "AglTools", env=env)
gw = GatewayStack(app, "AglGateway", ops_fn=tools.ops_fn, policy_mode=policy_mode, env=env)
agents = AgentsStack(app, "AglAgents", gateway=gw.gateway, model_id=model_id,
                     model_regions=model_regions, env=env)
# The policy stack always exists so every synth produces the same set of stacks.
# Its contents come from the .cedar files `make discover` renders from the live
# Gateway; before that it deploys empty.
policy = PolicyStack(app, "AglPolicy", engine=gw.engine, cedar_dir=cedar_dir, env=env)
if not rendered_policies(cedar_dir):
    print(f"AglPolicy has no policies: no rendered .cedar files in {cedar_dir}. "
          "Run `make discover`.", file=sys.stderr)

for s in [*data, tools, gw, policy, agents]:
    tags.apply(s, expires)

# `make check` runs synth with -c nag=true: the AWS Solutions rule pack reviews every
# resource, and any finding without a written acknowledgement fails the synth.
if app.node.try_get_context("nag") == "true":
    from cdk_nag import AwsSolutionsChecks

    cdk.Validations.of(app).add_plugins(AwsSolutionsChecks(app))

app.synth()
