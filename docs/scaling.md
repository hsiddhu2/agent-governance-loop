# Scaling the pattern

The pattern puts every tool call through one decision point: a Gateway with a policy engine in front of the tools. This page covers how that grows from two agents to many teams, what the service limits allow, and which controls a platform team keeps. Each claim is marked as measured in the account this was built in, or cited from AWS documentation. Measured results are from single runs unless a count is given.

## Three ways to grow

| | One team | Many teams, one account | Many accounts |
|---|---|---|---|
| Gateway | One | One per team | One, in the platform account |
| Policy engine | One | One per team | One, in the platform account, beside the Gateway |
| Who owns the rules | The team | Each team, starting from the platform's template | The platform team. Teams propose changes through its pipeline |
| Who owns the tools | The team | Each team | Each team, in its own account |
| State here | Built: two agents | The shared-engine variant measured. The per-team form is the same stack deployed again | Design only |

### One team

This is what the repo deploys: one Gateway and one policy engine. Each agent has its own client in the Gateway's user pool, so each is its own Cedar principal, and its own permit names only the tools it needs. The support agent has its own client, target, permit, screens and runtime. It shares the engine, the forbid, the trail and the collector. The access matrix (`make matrix`) checks every agent against every tool after each change.

Headroom: 1,000 Gateways per account, 100 targets per Gateway and 1,000 policies per engine ([AgentCore quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)). The tool-call rate is 200 per second per Gateway and 200 per second for the account. Both can be raised.

### Many teams, one account

Give each team its own Gateway and its own policy engine, both created from the platform team's template. Every rule in this pattern names the Gateway it applies to, so a new Gateway starts with no rules at all. The template is what makes it safe from the first call: it carries the standard forbids, such as the one on destructive tools, and the standard screens, rendered for the new Gateway as the templates in `policies/` are with `{{GATEWAY_ARN}}`. The team then adds the permits for its own agents and tools. Each Gateway also needs its own service role, allowed to call `bedrock-agentcore:AuthorizeAction` on that Gateway.

One engine shared by several Gateways also works, and it was tested here with a temporary second Gateway on the live engine. AWS pages disagree on whether this is allowed: the CLI reference says "Each policy engine can be associated with one Gateway (one engine per Gateway)" ([list-policy-engines](https://docs.aws.amazon.com/cli/latest/reference/bedrock-agentcore-control/list-policy-engines.html)), while the quotas page refers to "all gateways associated with the policy engine". What was measured:

- The second Gateway was accepted with the engine attached in ENFORCE and was READY within about 6 seconds, in one run.
- CreateGateway first checks that the new Gateway's role may call `bedrock-agentcore:AuthorizeAction` on the new Gateway, and refuses the create otherwise.
- With a policy engine attached, CreateGateway also assumes the role, so a role whose trust policy names a different Gateway is refused at create time. Without an engine, no trust check happens until a target is added.
- None of the first Gateway's policies applied on the second. The agent saw no tools there, and both an allowed tool and the purge were denied by default, not by the forbid.
- A permit and a forbid naming the second Gateway then worked there. From the create call to the first allowed tool call took about 31 seconds, policies created one at a time. The first Gateway's access matrix stayed 12 of 12 throughout.
- The engine does not list the Gateways attached to it.

A shared engine is not recommended. It shares the container and nothing else, since every rule still names one Gateway. Every team then draws on the same fixed limits: 1,000 policies, and a 400 KB Cedar schema that "applies to the combined Cedar schema generated from all tools across all gateways associated with the policy engine" ([AgentCore quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)). In this account a valid policy was refused while other policies were being created on the same engine, and creating them one at a time succeeded (see [Guardrail policies](guardrail-policies.md)). AWS has not confirmed the cause. So changes are made one at a time, and teams queue behind each other. And no one can read from the engine which Gateways depend on it.

### Many accounts

AWS guidance starts small: "Begin with the single-account model for exploration. Move to multi-account once you need environment separation." ([AWS Prescriptive Guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/best-practices.html)). For many teams, AWS describes a hub and spoke: "a central platform account, distributed LOB accounts, and AgentCore Gateway as the integration layer" ([multi-account agent with AgentCore Gateway](https://aws.amazon.com/blogs/machine-learning/build-a-multi-account-ai-agent-with-agentcore-gateway-and-mcp/)). Each team runs its tools as an MCP server in its own account. The platform account's Gateway registers each one as a target, and Policy in AgentCore evaluates every call at that Gateway, so the policy engine sits in the platform account with it. Teams own their tools and propose rule changes. The platform team reviews them and its pipeline deploys them. Attaching an engine from another account was not tested here, so do not plan on one. The same post recommends setting `allowedWorkloadConfiguration` on each team's runtime so it accepts calls only through the Gateway.

Two more things change at this scale. For a cross-account invocation of an agent runtime, AWS says "requests count against the resource owner’s per-account rate quotas" ([AgentCore quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)), where the owner is the account that owns the runtime. AWS does not say the same for Gateway tool calls. And the catalog can be shared across the organization with AWS Resource Access Manager ([sharing a registry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-cross-account-sharing.html)). None of this was built or tested here.

## Limits that shape the choice

From [AgentCore quotas](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html), per account per Region. Quotas change, so check the page before you plan:

| Limit | Value | Can be raised |
|---|---|---|
| Policy engines | 1,000 | No |
| Policies per engine | 1,000 | No |
| Size of one policy | 10 KB | No |
| Policies per resource within one engine | 200 KB in total | No |
| Cedar schema per engine, across all its Gateways | 400 KB | No |
| Gateways | 1,000 | Yes |
| Targets per Gateway | 100 | Yes |
| Tool calls and tool lists, per Gateway and per account | 200 per second each | Yes |
| CreatePolicy, UpdatePolicy, DeletePolicy | 5 per second | No |
| Registries | 10 | Yes |

Every Policy resource limit is fixed. AWS says the schema size grows with the number of tools and the complexity of their input parameters.

## Keeping enforcement on

Anyone who can call `UpdateGateway` can switch a Gateway's engine to LOG_ONLY or detach it, and then every tool call succeeds whatever the forbid policies say. AWS pages disagree on whether this can be prevented below the action level. The page on enforcement modes says "No separate action or condition key protects the `mode` field beyond `bedrock-agentcore:UpdateGateway`" ([Policy enforcement modes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-enforcement-modes.html)). The page on Gateway condition keys lists `bedrock-agentcore:PolicyEngineMode` for `CreateGateway` and `UpdateGateway` ([condition keys](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/security-gateway-condition-keys.html)). The [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html) defines the key, and its UpdateGateway entry lists only `aws:ResourceTag/${TagKey}`.

It was tested here with a temporary role whose only Deny was the first statement below, on a temporary Gateway:

| UpdateGateway call | Result |
|---|---|
| Set the mode to LOG_ONLY | Refused, explicit deny. The Gateway stayed in ENFORCE |
| Keep ENFORCE, change the description | Allowed |
| Leave out the policy engine configuration | Refused, explicit deny. The engine stayed attached |

A negated condition on a key that is absent from the request evaluates to true, so one statement covers both the switch and the detach. The test used an identity policy. IAM evaluates the Deny in a service control policy the same way, but it was not run as one, because the account this was built in is not an organization's management account.

A platform team can hold every team's Gateway in ENFORCE by adding statements along these lines to a service control policy:

```json
[
  {
    "Sid": "RequireEnforcedPolicyEngine",
    "Effect": "Deny",
    "Action": ["bedrock-agentcore:CreateGateway", "bedrock-agentcore:UpdateGateway"],
    "Resource": "*",
    "Condition": {"StringNotEquals": {"bedrock-agentcore:PolicyEngineMode": "ENFORCE"}}
  },
  {
    "Sid": "PolicyChangesOnlyFromThePipeline",
    "Effect": "Deny",
    "Action": [
      "bedrock-agentcore:CreatePolicy",
      "bedrock-agentcore:UpdatePolicy",
      "bedrock-agentcore:DeletePolicy",
      "bedrock-agentcore:UpdatePolicyEngine",
      "bedrock-agentcore:DeletePolicyEngine"
    ],
    "Resource": "*",
    "Condition": {"ArnNotLike": {"aws:PrincipalArn": "arn:aws:iam::*:role/policy-pipeline"}}
  }
]
```

The first statement was measured on `UpdateGateway` as described above. On `CreateGateway` it is untested, and as written it also refuses a Gateway created without an engine, which is the intent. The second statement is a design, not tested: it limits policy changes to one pipeline role, named here as an example, using only the global `aws:PrincipalArn` key. The LOG_ONLY window this pattern uses to discover a new Gateway's tools then needs a reviewed exception, run by the pipeline and closed by it.
