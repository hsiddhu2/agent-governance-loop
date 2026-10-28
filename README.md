# agent-governance-loop

Independent community project. Not sponsored, endorsed, or maintained by AWS.

## Summary

An AI agent can call any tool its credentials reach, and the model decides which. This pattern puts one chokepoint between agents and their tools: an Amazon Bedrock AgentCore Gateway with a policy engine. Cedar policy decides which agent may call which tool, guardrail screens in the same engine withhold responses that carry sensitive data, and every decision is recorded with the policy that made it. An evidence collector turns those records into a pack an auditor can read.

It deploys with one command into a sandbox account and was tested there end to end. Two agents, a claims operations agent and a support agent, are the test bench. They exist to exercise the controls, not as a product.

Status: working in a sandbox account. After a destroy, a deploy into the account with no pattern resources left (CDK bootstrap kept) gave the same outcomes for the access matrix, the catalog find, the three agent scenarios, the screen matrix and the ticket screens. That full `make deploy` took about 18.5 minutes, once, and `make destroy` about 8 minutes, once.

## When to use it

- Agents call tools that change or expose data you are accountable for, and you need a control that holds whatever the model decides.
- Several agents share tools, and each may use only some of them.
- Someone outside the team, an auditor or a risk function, needs evidence of who called what and what was allowed.

### What it does not do

The pattern decides who may call a tool and what may come back. It does not cover these on its own:

- **Rate and cost limits.** How often or how much a tool is called is a quota, not an authorization. The AWS pattern in [Related resources](#related-resources) covers it.
- **Data with no guardrail category.** A date of birth or a diagnosis cannot be screened. Keep it out of the tool's response. See [Design review points](#design-review-points).
- **Least privilege on the tools.** The policy is a second control. Each tool's own role should still allow only what it needs.

## The pattern

```
agent (AgentCore Runtime)
  -> AgentCore Gateway  -- inbound: JWT, one client per agent
       policy engine:   Cedar permit and forbid decide the call
                        guardrail screens decide the response
  -> tool (Lambda)       -- outbound: the Gateway's role
records: decision spans in CloudWatch, every call in a CloudTrail trail
evidence: make evidence reads both and writes a pack
```

What each part controls, in the order it is set up:

| # | Part | Controls | Set up by | Where |
|---|---|---|---|---|
| 1 | Call trail | Every call to the Gateway, with the caller's token claims, in its own CloudTrail trail | `make deploy-base` | [infra/stacks/audit_stack.py](infra/stacks/audit_stack.py) |
| 2 | Tools | What each tool can reach. Each runs as its own role in a private network | `make deploy-base` | [tools/](tools/), [infra/stacks/tools_stack.py](infra/stacks/tools_stack.py) |
| 3 | Gateway and its inbound auth | Which agent is calling. Each agent has its own client, and its client id is its Cedar principal. The policy engine is attached here, with decision spans sent to CloudWatch | `make deploy-base` | [infra/stacks/gateway_stack.py](infra/stacks/gateway_stack.py) |
| 4 | Cedar policy | Which tools each agent may call. Default deny, plus an explicit forbid on the destructive tool so a trace names it | `make discover`, `make deploy-policy` | [policies/cedar/](policies/README.md) |
| 5 | Guardrail screens | Which responses are withheld, by sensitive-data category | `make discover`, `make deploy-policy` | [policies/guardrails/](policies/README.md), [docs/guardrail-policies.md](docs/guardrail-policies.md) |
| 6 | Enforcement | Whether the policy engine applies its decisions or only records them | `make enforce` | [scripts/policy_mode.py](scripts/policy_mode.py) |
| 7 | Agents | Who may invoke each agent. Each runtime accepts only tokens issued to its own console | `make deploy-agents` | [infra/stacks/agents_stack.py](infra/stacks/agents_stack.py) |
| 8 | Agent Registry catalog | Which agents and tools are approved and discoverable. Finding a tool grants nothing | `make deploy-registry`, `make approve-catalog` | [infra/stacks/registry_stack.py](infra/stacks/registry_stack.py) |
| 9 | Evidence pack | What an auditor can read: decisions and calls, mapped to what regulators ask | `make evidence` | [collector/](collector/README.md) |

## The test bench

Two agents and their data exist to exercise the controls above, on real infrastructure with synthetic data. They are not a product.

| | Ops agent | Support agent |
|---|---|---|
| Role | Answers claims operations questions | Reads customer tickets and drafts replies |
| May call | `list_env`, `get_claims_store`, `get_claim`, `get_claim_record` | `get_ticket`, `get_claim` |
| Denied | `purge_claims`, by default deny and by an explicit forbid. `get_ticket` | Every other tool, the purge included |
| Reads | The claims stores, staging and production | The ticket stores, and claim summaries through `get_claim` |

The data, written by `make seed`: 50 synthetic claims in each claims store, 20 probe records in staging that each carry one kind of sensitive field, and 12 tickets in each ticket store. See [scripts/synthetic.py](scripts/synthetic.py).

Two tools read the same claim on purpose. `get_claim` returns only what a status question needs. `get_claim_record` returns the whole claim file, deliberately not minimized, to show what a screen catches and what it cannot.

The scenarios, and the control each one exercises:

| Command | What happens | Control it shows |
|---|---|---|
| `make attack SCENARIO=claims-cleanup` | The ops agent is asked to purge the staging claims store. IAM allows the purge on purpose | The Cedar forbid denies it, whatever the model decides, and the trace names the policy |
| `make attack SCENARIO=ticket-injection` | The support agent reads a ticket that tells its reader to purge the claims store | The purge is not listed to the support agent, and the same call made directly with its credential is denied |
| `make attack SCENARIO=claim-file` | The ops agent asks for a full claim file that carries a Social Security number | The government identifier screen withholds the whole response and names itself |
| `make matrix` | Each agent's credential calls each tool, without the model | Each agent reaches only its own tools |
| `make find` | The support agent finds the purge tool in the catalog, then calls it | Finding a tool grants nothing |

## Things to know before you build

What we found while building and testing this pattern in a live sandbox account. Each point links to evidence in this repo. "Measured once" means a single run that the repo describes but does not reproduce with a script. The groups follow the order the parts are set up.

### Gateway

1. **Under ENFORCE, discovery hides what policy does not allow.** tools/list returns only the tools the caller may call, so the forbidden purge is invisible to every agent. Adding or renaming a tool needs LOG_ONLY first, or it disappears. Evidence: [Quickstart](#quickstart), [scripts/policy_mode.py](scripts/policy_mode.py).
2. **A denied call and a withheld response look different on the wire.** A deny comes back as HTTP 200 with JSON-RPC error -32002. A withheld response comes back as HTTP 403 with the same code. A client that checks only the status code misses every deny. Evidence: the sample pack's [callers.json](evidence/examples/agl-gateway-two-agents/callers.json).

### Policy engine

3. **One policy engine can serve several Gateways, but its policies do not carry across.** A forbid written for one Gateway protects nothing on another. An IAM Deny on UpdateGateway when `bedrock-agentcore:PolicyEngineMode` is not ENFORCE refused a switch to LOG_ONLY and a detach, on one test Gateway. The enforcement-modes page says no separate action or condition key protects the mode beyond `bedrock-agentcore:UpdateGateway`. Measured once. See [docs/scaling.md](docs/scaling.md).

### Guardrail screens

4. **Guardrail statements are not plain Cedar.** They must be created in the API's `policy` member, not `cedar`, and comment lines before the effect make the create fail. Evidence: [docs/guardrail-policies.md](docs/guardrail-policies.md), [tests/policies/test_policy_statement.py](tests/policies/test_policy_statement.py).
5. **`count()` fires on categories the screen does not name.** On two records, a screen naming only Canadian and UK health numbers matched an SSN record and an email-only record. Test each category by name. Evidence: [docs/guardrail-policies.md](docs/guardrail-policies.md), `scripts/screen_matrix.py`.
6. **A screen is not a block.** The tool runs and reads the data, then the Gateway withholds its response. Keeping data out of a response is the tool's job. The screen is the backstop. AWS documents it, and three withheld calls here carried the tool's own span.

### Tools behind the Gateway

7. **A tool behind a screen needs an error contract.** A Lambda tool that raises reaches the caller as "An internal error occurred". Only an MCP `isError` result keeps the tool's message, and a screen withholds that result because it has none of the fields the screen reads. The Gateway does not enforce the tool's `outputSchema`. Measured twice. See [docs/guardrail-policies.md](docs/guardrail-policies.md).

### Observability and evidence

8. **A withheld response leaves no decision in the trace.** The trace shows only the request's ALLOW. The withhold, and the screen that did it, are in the call's CloudTrail event. A dashboard built on decision spans undercounts screens. AgentCore also publishes a SuppressOutputs metric, the "Number of outputs suppressed by policies using the `suppressOutput` effect", to the AWS/Bedrock-AgentCore namespace. Evidence: [docs/screen-coverage.md](docs/screen-coverage.md), the sample pack's `suppressedBy` fields.
9. **A deny on a screened tool may not name the forbid.** It can report missing guardrail fields instead. Read the decision's determining policies, not its message. Evidence: the sample pack's [decisions.json](evidence/examples/agl-gateway-two-agents/decisions.json).

### Building with the CDK

10. **The role the CDK Gateway construct writes has a trust statement with no condition, and a Gateway outside this pattern's name used it, until its trust policy is replaced** ([aws-cdk#38780](https://github.com/aws/aws-cdk/issues/38780)). Evidence: [tests/infra/test_gateway_role_trust.py](tests/infra/test_gateway_role_trust.py).

## Quickstart

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22 or later, AWS CDK CLI 2.1144 or later, and an AWS account with CloudWatch Transaction Search enabled in us-east-1.

```
scripts/setup.sh
source .venv/bin/activate
make deploy
make seed
make attack SCENARIO=claims-cleanup
make attack SCENARIO=ticket-injection
make attack SCENARIO=claim-file
make matrix
make find
make trace
make evidence
make reset
make destroy
```

`make seed` writes 50 synthetic claims to each claims store, 20 probe records to staging, each carrying one kind of field, and 12 support tickets to each ticket store. Social Security numbers start with 666, phone numbers are 555-0100 to 555-0199, email addresses use example.com, card numbers are published test numbers, and the routing number is 500000005. A licence number is the surname's initial and random digits. Passport and bank account numbers are random digits. See [`scripts/synthetic.py`](scripts/synthetic.py).

`make deploy` runs seven steps in order:

1. `deploy-base`: KMS keys, a trail of every call to the Gateway, network, claims and ticket stores, the two tool functions, and the Gateway with its policy engine. A first deploy starts the engine in LOG_ONLY. Later deploys keep the mode it runs in.
2. `discover`: reads tool names from the live Gateway and renders the Cedar files from them.
3. `deploy-policy`: adds the policies to the engine.
4. `enforce`: checks that every rendered policy exists in the engine with status ACTIVE and that a fresh tools/list policy span allows at least one tool, then switches the Gateway to ENFORCE.
5. `deploy-agents`: the ops and support agents on AgentCore Runtime, behind their own user pool. Each runtime accepts only tokens issued to its own console client.
6. `deploy-registry`: the catalog, with its own key. Its records are published as drafts.
7. `approve-catalog`: approves each record that matches what is deployed, and rejects the rest with the reason.

Options: `make attack MODE=direct` calls the tool with the agent's credential instead of going through the agent. `make evidence SINCE=7d REDACT=--redact` sets how far back the pack reads and makes one you can share. See [scripts/](scripts/README.md).

Enforcement changes only through `make enforce` and `make log-only`. Every other deploy keeps the mode the Gateway already runs in.

Under ENFORCE, tools/list hides tools that no policy allows, including the forbidden purge. Re-running `make deploy` keeps the names the last discovery read, as long as every tool still listed has the same name. To add or rename a tool, run `make log-only` first.

## Project layout

| Path | What it holds |
|---|---|
| [`policies/`](policies/README.md) | The policy templates: permits and forbids in `cedar/`, output screens in `guardrails/` |
| [`infra/`](infra/) | The CDK app and its stacks |
| [`tools/`](tools/) | The two tool functions behind the Gateway, with their tool schemas |
| [`agents/`](agents/) | The two test-bench agents that run on AgentCore Runtime |
| [`scripts/`](scripts/README.md) | Deploy steps, checks, test-bench scenarios, data and teardown, grouped by role |
| [`collector/`](collector/README.md) | The evidence collector behind `make evidence` |
| [`tests/`](tests/README.md) | Offline tests, grouped by the part of the pattern they protect |
| [`docs/`](docs/) | Guides: guardrails, screen coverage, scaling, the controls map, design review points |
| [`evidence/examples/`](evidence/examples/) | A redacted sample evidence pack |
| `Makefile` | Every command in this README |
| `cdk.json` | Tells the CDK CLI how to build the app. `app` is the command it runs, `infra/app.py`. `region` is read by the app. `@aws-cdk/core:defaultCrossStackReferences: weak` passes values between stacks in a way that lets one stack be replaced without CloudFormation blocking it on another stack's export. `@aws-cdk/core:validateAgainstDefaultRules` turns template validation findings into build failures |
| `pyproject.toml` | Python dependencies and lint settings |

## Evidence for an auditor

`make evidence` reads the live account and writes a pack that maps what regulators ask of agents to what the account shows, as PASS, FAIL or GAP. See [collector/](collector/README.md). A redacted sample from a full deploy is in [evidence/examples/agl-gateway-two-agents/](evidence/examples/agl-gateway-two-agents/summary.md). Start with `summary.md`. [docs/controls-map.md](docs/controls-map.md) gives the sources for each ask.

A pack supports evidence for a control. It does not show compliance on its own.

## Built to production practice

What the pattern sets by default:

- Customer managed keys on the stores, logs, trail and catalog. Data masking and a set retention on every log group the stacks own.
- Claims stores kept as stores of record: deletion protection, point-in-time recovery and daily backups.
- A trail of every call to the Gateway, with log file validation.
- Tool functions in private subnets whose only route out is the DynamoDB endpoint.
- Each agent's runtime accepts only tokens issued to its own console client. No secret is in agent code or in a stack output.
- Enforcement changes only through `make enforce` and `make log-only`.

Every `make check` and every deploy reviews each resource with two [cdk-nag](https://github.com/cdklabs/cdk-nag) rule packs, AWS Solutions and NIST SP 800-53 Rev 5, plus CloudFormation template validation. A finding stops the build unless the code accepts it next to the resource with a written reason.

`make check` runs after every change and needs no AWS account:

- `ruff` lint and the offline tests in [`tests/`](tests/README.md) and `collector/tests/`. `make test` runs the tests alone.
- A clean synth reviewed by two [cdk-nag](https://github.com/cdklabs/cdk-nag) rule packs: AWS Solutions, and NIST SP 800-53 Rev 5. Every finding is either fixed or acknowledged next to the resource with the reason it stands. Template validation issues also fail the synth.
- A check that every acknowledged rule appears in the table under [Design review points](#design-review-points), and that the table lists nothing that is no longer acknowledged.
- A check that no stack output carries a secret. CDK passes values between stacks as outputs, which anyone who can describe the stack can read.
- A synth with no rendered policies, compared with the normal one. Only the policy stack may differ.

Deploys run the same rule packs, so nothing ships without them. Each deploy also compares its templates with the live stacks and stops if a resource would change type under the same logical id, which CloudFormation cannot update. The templates it checked are the ones it deploys.

## Design review points

Where this pattern does not meet a rule, or stops short of production, the reason is below. Review each one before you build your own. [docs/design-review.md](docs/design-review.md) explains each in plain terms: what happens, why, what blocks a fix, and what a production team does. They fall into three kinds:

- **Choices to change for production.** For example, the ops tool role may purge every claims store on purpose, the trail stays in one account, and no person signs in to the console.
- **Limits from AWS and the CDK.** For example, the Service Authorization Reference lists no resource types for `bedrock:InvokeGuardrailChecks`, and some data has no guardrail category.
- **Rules that do not fit.** For example, password and MFA rules on user pools that have no human users.

Rules not met. `make check` fails if a rule accepted in code is missing from this table, or the table lists one that is no longer accepted.

| Rule | Where | Why it stands |
|---|---|---|
| `AwsSolutions-IAM5` | Tool, Gateway and agent roles | Wildcards the services require: actions without resource-level permissions (including `bedrock:InvokeGuardrailChecks`), CDK asset keys, and names assigned at deploy time. The tool role's purge on every claims table is deliberate: it is the gap the Cedar policy closes. Each one is listed next to its resource. |
| `AwsSolutions-IAM4` | Backup selection roles, deploy-time function | The AWS managed service policy AWS Backup documents for running backups. The basic execution policy on CDK's deploy-time custom resource function. |
| `NIST.800.53.R5-IAMNoInlinePolicy` | Gateway, Runtime, flow log, trail delivery and deploy-time function roles | The constructs write their own grants as inline default policies. Permissions this repo adds are in managed policies. |
| `NIST.800.53.R5-LambdaDLQ` | Tool function, deploy-time function | The Gateway invokes the tool functions synchronously, so a failure goes back to the caller and a queue would never receive anything. CloudFormation invokes the deploy-time functions asynchronously and waits for their answer, so a failure fails the deploy and is in the function's logs. |
| `NIST.800.53.R5-LambdaConcurrency` | Deploy-time functions | CDK's custom resource function, once in the Gateway stack to hand the generated client secret to AgentCore Identity, and once in the agents stack to configure the runtime's log group. It runs only during a deploy. The tool function has a concurrency limit. |
| `NIST.800.53.R5-LambdaInsideVPC` | Deploy-time functions | Same functions. A choice, not a limit: inside the VPC they would need interface endpoints for Cognito and CloudWatch Logs, billed for every hour they exist, for calls that last seconds per deploy. The tool functions run in private subnets. |
| `F3002` | VPC flow log, registry | Template validation findings. The flow log one is acknowledged by aws-cdk-lib itself: the flow log destination options are accepted in camelCase. The registry's encryption key property is in the live CloudFormation schema but not yet in the one aws-cdk-lib bundles. |
| `F3003` | VPC flow log | Same acknowledgement, from aws-cdk-lib. |
| `W3010` | Network stack | Acknowledged by aws-cdk-lib: availability zones read from the stack. |
| `AwsSolutions-S1` | Gateway trail bucket | Server access logs. Only CloudTrail writes to the bucket. Reads of its objects are data events, which this pattern does not record. A production trail delivers to a central log archive account with its own access logs. |
| `NIST.800.53.R5-S3BucketLoggingEnabled` | Gateway trail bucket | Same rule as `AwsSolutions-S1`, from the NIST pack. |
| `NIST.800.53.R5-S3BucketReplicationEnabled` | Gateway trail bucket | Sandbox. A production trail delivers to a central log archive account. |
| `AwsSolutions-COG1` | Gateway and operator user pools | Password policy. Neither pool has human users. Their clients are services using the client-credentials flow. |
| `AwsSolutions-COG2` | Gateway and operator user pools | MFA. Same reason. |
| `AwsSolutions-COG8` | Gateway and operator user pools | Sign-in threat protection. Same reason. |

## Troubleshooting

| Issue | Cause | What to do |
|---|---|---|
| An agent sees no tools after a deploy | Under ENFORCE, discovery hides tools no policy allows. A renamed tool has no policy yet | `make log-only`, then `make deploy`. Its enforce step switches the Gateway back to ENFORCE |
| A tool call returns "Output blocked by policy" for a record that does not exist | The tool returned an error result, which has no fields for the screen to read | Answer a not-found in the tool's declared shape, every field filled. See [docs/guardrail-policies.md](docs/guardrail-policies.md) |
| A guardrail policy fails to create with "policy effect must be `permit` or `forbid`" | Comment lines before the effect | Remove them, or create it as the `policy` member without comments |
| The evidence pack shows a GAP on calls right after a deploy | On a new trail, the first collection can show a GAP and a later one pass | Collect again after a few minutes |
| CreateGateway fails naming GenesisPolicyEngineCheck | The new Gateway's role may not call AuthorizeAction on the new Gateway | Give the role AuthorizeAction on the new Gateway's ARN. See [docs/scaling.md](docs/scaling.md) |

## Cost

What this deploys is billed by use: model calls from the agents, AgentCore Runtime, Gateway and Policy requests, Lambda, DynamoDB on demand, CloudTrail data events, and CloudWatch Logs. KMS keys and backups have a monthly charge while they exist. There is no NAT gateway, and the only VPC endpoint is the DynamoDB gateway endpoint, which has no charge. Every resource is tagged `project=agl`, so Cost Explorer can show what it costs in your account. Run `make destroy` when you are done.

Pricing: [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/pricing/), [AWS CloudTrail](https://aws.amazon.com/cloudtrail/pricing/), [AWS KMS](https://aws.amazon.com/kms/pricing/).

## Related resources

- [Governing AI agent tool quotas with AWS Agent Registry and Amazon Bedrock AgentCore Gateway](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/govern-tool-access-with-aws-agent-registry-metadata.html), an AWS Prescriptive Guidance pattern for rate and cost limits per tool. It complements this one, which governs who may call a tool and what may come back.
- [Enforce content safety with guardrails in AgentCore Policy](https://github.com/aws-samples/sample-native-guardrails-for-bedrock-agentcore), an AWS sample of guardrails in policy.
- [Policy in Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) and [Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html).
- [docs/scaling.md](docs/scaling.md): from one team to many.

## Notices

This repository is shared for information and learning. It runs on real infrastructure with synthetic data, and no number in it is a production claim. It is not intended for production accounts or production data as it stands. Test, secure and adapt it to your own standards before you rely on any part of it. Deploying it creates AWS resources that are billed to your account. AWS services change, so check each behavior described here against the current AWS documentation.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.

## Citation

If you use or build on this pattern, cite it with the metadata in `CITATION.cff`
(GitHub's "Cite this repository" button).

## Maintainer

Maintained by Harpreet S. Siddhu.
