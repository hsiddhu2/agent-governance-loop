import sys
from pathlib import Path

import aws_cdk as cdk

from stacks import tags
from stacks.agents_stack import AgentsStack
from stacks.data_stack import DataStack
from stacks.gateway_stack import GatewayStack
from stacks.policy_stack import PolicyStack, rendered_policies
from stacks.tools_stack import ToolsStack

app = cdk.App()
# Fixed on purpose. This project only runs in us-east-1.
env = cdk.Environment(region="us-east-1")
expires = app.node.try_get_context("expires")
cedar_dir = Path(app.node.try_get_context("cedar_dir") or "policies/cedar")

data = DataStack(app, "AglData", env=env)
tools = ToolsStack(app, "AglTools", tables=data.tables, env=env)
gw = GatewayStack(app, "AglGateway", ops_fn=tools.ops_fn, env=env)
agents = AgentsStack(app, "AglAgents", gateway=gw.gateway, env=env)
stacks = [data, tools, gw, agents]

# Cedar is rendered from tool names the live Gateway reports, so the policy
# stack only exists once `make discover` has produced the .cedar files.
if rendered_policies(cedar_dir):
    stacks.append(PolicyStack(app, "AglPolicy", engine=gw.engine, cedar_dir=cedar_dir, env=env))
else:
    print(f"AglPolicy skipped: no rendered .cedar files in {cedar_dir}. Run `make discover`.",
          file=sys.stderr)

for s in stacks:
    tags.apply(s, expires)

app.synth()
