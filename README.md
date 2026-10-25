# agent-governance-loop

Independent community project. Not sponsored, endorsed, or maintained by AWS.

A deployable governance pattern for AI agents on Amazon Bedrock AgentCore. One command deploys two agents on AgentCore Runtime behind a Gateway with Cedar policy, an approved catalog of the agents and the Gateway's tools, a decision record in CloudWatch that names the policy behind each allow and deny, and claims and ticket stores kept as stores of record.

An evidence pack answers an auditor's questions from the live account (`make evidence`, see [collector/](collector/README.md)). A redacted sample from a full deploy is in [evidence/examples/agl-gateway-two-agents/](evidence/examples/agl-gateway-two-agents/summary.md). Start with `summary.md`.

Bedrock Guardrails in policy screen what a tool returns at the Gateway. Six screens are deployed. On the full claim file, the government identifier screen is enforced and withholds a response it matches, and three others record what they would withhold without withholding it. On support tickets, the government identifier and financial screens are both enforced. See [docs/guardrail-policies.md](docs/guardrail-policies.md), and [docs/screen-coverage.md](docs/screen-coverage.md) for what each screen catches, field by field.

[docs/scaling.md](docs/scaling.md) covers growing from one team to many: a Gateway and a policy engine per team, the service limits, and keeping every Gateway enforced.

Status: working in a sandbox account. Deployed there from an empty account and checked end to end: each agent against each tool, the catalog, every screen and each attack scenario gave the results described below. A full `make deploy` took about 19 minutes, and `make destroy` about 8.

## What it proves

Control gaps that block agents in regulated operations, reproduced with synthetic claims data on real infrastructure.

- A claims operations agent reaches a tool that can purge every claim record. The claims stores are protected as stores of record: deletion protection, point-in-time recovery, daily backups and a customer-managed key. None of that stops a purge, and IAM allows it. Cedar policy at the Gateway denies it whatever the model decides, and the CloudWatch trace names the policy that made the decision.
- Two tools read the same claim. `get_claim` returns what an agent needs to answer a status question: status, type, amount, the last four digits of the Social Security number and the birth year. `get_claim_record` returns the whole claim file, with every identifier and health detail in it. It is deliberately not minimized, to show what a guardrail does and does not catch when an API returns too much. Guardrails in policy screen its response at the Gateway. When the government identifier screen matches, the Gateway withholds the whole response, not only the identifier, and the caller gets an error that names the screen. Some of what a claim file holds cannot be screened at all (see Limitations). So the control is the tool that returns only what the caller needs, as `get_claim` does. The screen is the backstop when an API gets that wrong.
- A support agent reads customer tickets. It is its own Cedar principal, may call only `get_ticket` and `get_claim`, and is denied every other tool (`make matrix` checks each agent against each tool). One ticket carries instructions telling whoever reads it to purge the claims store. The purge tool is not listed to the support agent, so the injected call never reached the Gateway, and the same call made directly with the support agent's credential is denied by the forbid. A ticket where a customer pasted a Social Security or card number is withheld by the ticket screens.
- The agents and the Gateway's tools are recorded in an Agent Registry catalog. Each record is published as a draft and approved only when it matches what is deployed (`make approve-catalog`). Finding a tool in the catalog grants nothing: `make find` searches for the purge tool and calls it as the support agent, and the Gateway denies it.

[docs/controls-map.md](docs/controls-map.md) maps what insurance, financial and AI regulators ask of agents to the control here that produces evidence for each ask, with sources.

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

`make seed` writes 50 synthetic claims to each claims store, 20 probe records to staging, each carrying one kind of field, and 12 support tickets to each ticket store. Every value is fictional and drawn from ranges that belong to nobody, such as Social Security area 666, which is never assigned. See [`scripts/synthetic.py`](scripts/synthetic.py).

`make deploy` runs seven steps in order:

1. `deploy-base`: KMS keys, a trail of every call to the Gateway, network, claims and ticket stores, the two tool functions, and the Gateway with its policy engine. A first deploy starts the engine in LOG_ONLY. Later deploys keep the mode it runs in.
2. `discover`: reads tool names from the live Gateway and renders the Cedar files from them.
3. `deploy-policy`: adds the policies to the engine.
4. `enforce`: checks in LOG_ONLY that the policies allow at least one tool, then switches the Gateway to ENFORCE.
5. `deploy-agents`: the ops and support agents on AgentCore Runtime, behind their own user pool. Each runtime accepts only tokens issued to its own console client.
6. `deploy-registry`: the catalog, with its own key. Its records are published as drafts.
7. `approve-catalog`: approves each record that matches what is deployed, and rejects the rest with the reason.

Enforcement changes only through `make enforce` and `make log-only`. Every other deploy keeps the mode the Gateway already runs in.

Under ENFORCE, tools/list hides tools that no policy allows, including the forbidden purge. Re-running `make deploy` keeps the names the last discovery read, as long as every tool still listed has the same name. To add or rename a tool, run `make log-only` first.

## Checks

`make check` runs after every change and needs no AWS account:

- `ruff` lint and the offline tests in `tests/`.
- A clean synth reviewed by two [cdk-nag](https://github.com/cdklabs/cdk-nag) rule packs: AWS Solutions, and NIST SP 800-53 Rev 5. Every finding is either fixed or acknowledged next to the resource with the reason it stands. Template validation issues also fail the synth.
- A check that every acknowledged rule appears in the deviations table below, and that the table lists nothing that is no longer acknowledged.
- A check that no stack output carries a secret. CDK passes values between stacks as outputs, which anyone who can describe the stack can read.
- A synth with no rendered policies, compared with the normal one. Only the policy stack may differ.

Deploys run the same rule packs, so nothing ships without them. Each deploy also compares its templates with the live stacks and stops if a resource would change type under the same logical id, which CloudFormation cannot update. The templates it checked are the ones it deploys.

## Deviations from production

Each row is a rule this repo does not meet, and why. `make check` fails if a rule is acknowledged in code and missing here, or listed here and no longer acknowledged. [docs/known-gaps.md](docs/known-gaps.md) explains each row and each limitation below in plain terms: what happens, why, what blocks a fix, and what a production team does.

| Rule | Where | Why it stands |
|---|---|---|
| `AwsSolutions-IAM5` | Tool, Gateway and agent roles | Wildcards the services require: actions without resource-level permissions (including `bedrock:InvokeGuardrailChecks`), CDK asset keys, and names assigned at deploy time. The tool role's purge on every claims table is deliberate: it is the gap the Cedar policy closes. Each one is listed next to its resource. |
| `AwsSolutions-IAM4` | Backup selection roles, deploy-time function | The AWS managed service policy AWS Backup documents for running backups. The basic execution policy on CDK's deploy-time custom resource function. |
| `NIST.800.53.R5-IAMNoInlinePolicy` | Gateway, Runtime, flow log, trail delivery and deploy-time function roles | The constructs write their own grants as inline default policies. Permissions this repo adds are in managed policies. |
| `NIST.800.53.R5-LambdaDLQ` | Tool function, deploy-time function | Both are invoked synchronously. A dead-letter queue receives only failed asynchronous events, so failures go back to the caller and to the logs. |
| `NIST.800.53.R5-LambdaConcurrency` | Deploy-time functions | CDK's custom resource function, once in the Gateway stack to hand the generated client secret to AgentCore Identity, and once in the agents stack to configure the runtime's log group. It runs only during a deploy. The tool function has a concurrency limit. |
| `NIST.800.53.R5-LambdaInsideVPC` | Deploy-time functions | Same functions. A choice, not a limit: inside the VPC they would need interface endpoints for Cognito and CloudWatch Logs, billed for every hour they exist, for calls that last seconds per deploy. The tool functions run in private subnets. |
| `F3002` | VPC flow log, registry | Template validation findings. The flow log one is acknowledged by aws-cdk-lib itself: the flow log destination options are accepted in camelCase. The registry's encryption key property is in the live CloudFormation schema but not yet in the one aws-cdk-lib bundles. |
| `F3003` | VPC flow log | Same acknowledgement, from aws-cdk-lib. |
| `W3010` | Network stack | Acknowledged by aws-cdk-lib: availability zones read from the stack. |
| `AwsSolutions-S1` | Gateway trail bucket | Server access logs. Only CloudTrail writes to the bucket, and reads of it are recorded by the account trail. A production trail delivers to a central log archive account with its own access logs. |
| `NIST.800.53.R5-S3BucketLoggingEnabled` | Gateway trail bucket | Same rule as `AwsSolutions-S1`, from the NIST pack. |
| `NIST.800.53.R5-S3BucketReplicationEnabled` | Gateway trail bucket | Sandbox. A production trail delivers to a central log archive account. |
| `AwsSolutions-COG1` | Gateway and operator user pools | Password policy. Neither pool has human users. Their clients are services using the client-credentials flow. |
| `AwsSolutions-COG2` | Gateway and operator user pools | MFA. Same reason. |
| `AwsSolutions-COG8` | Gateway and operator user pools | Sign-in threat protection. Same reason. |

## Limitations

Each limitation is explained with an example in [docs/known-gaps.md](docs/known-gaps.md).

This is a sandbox pattern. The claims stores are real and their records can be purged. Rows are synthetic. No number in this repo is a production claim.

The ops console is a service that calls the agent with the client-credentials flow. No person signs in in front of it, so a request is tied to the console, not to the person who asked. A production deployment puts user sign-in with MFA in front of the console.

Keys, log groups, user pool and claims stores are removed with the stacks so the sandbox can be torn down. A production deployment retains them, and keeps logs for its audit period instead of 30 days. `make destroy` turns deletion protection off and empties the backup vaults first, on purpose. AgentCore creates the runtime's own log group, so the stacks set its key, masking and retention at deploy time but do not own it, and `make destroy` deletes it last. CDK's deploy-time functions write to log groups the stacks own, with the same key, masking and retention. Any group Lambda created for them earlier, named after its stack, is deleted last as well.

Calls to the Gateway are CloudTrail data events, which no trail records unless asked. This pattern adds its own trail for them, in the same account, with log file validation, its own key, and a copy in CloudWatch Logs. Each event names the tool and the caller's token claims, with arguments and results redacted by the service. Management events stay with the trail the account already has. A production deployment adds the Gateway data events to its organization trail, which delivers to a central log archive account, and keeps the files under Object Lock for its audit period instead of 30 days.

Trace spans in `aws/spans`, where the Gateway's policy decisions land, are encrypted with the AWS owned key and have no data masking. A production deployment sets a customer managed key for X-Ray, which is an account-wide setting. Whether a masking policy can be set on `aws/spans` has not been tested here.

Guardrails in policy have no category for a date of birth or for US health information, such as a medical record number, a diagnosis or an ICD-10 code. Neither can be screened. See [docs/guardrail-policies.md](docs/guardrail-policies.md#what-cannot-be-screened).

On the full claim file, only the government identifier screen is enforced. The contact details, financial and health identifier screens run in LOG_ONLY: they record what they would withhold and withhold nothing.

Catalog approval is automated: `make approve-catalog` checks each record against the deployed resources. A production team runs that step under a role that can change a record's status and cannot publish one, or puts a person in it.

In its default form, the CDK Gateway construct's service role can be used by any Gateway in the account ([aws-cdk#38780](https://github.com/aws/aws-cdk/issues/38780)). The Gateway stack replaces the role's trust policy with the statement limited to this Gateway, until the construct is fixed.

When a screen withholds a response, the trace shows only the request's ALLOW. The withheld response, and the screen that withheld it, are recorded in the call's CloudTrail event, so the evidence pack reads them from the trail.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.

## Citation

If you use or build on this pattern, cite it with the metadata in `CITATION.cff`
(GitHub's "Cite this repository" button).

## Maintainer

Maintained by Harpreet S. Siddhu.
