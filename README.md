# agent-governance-loop

Independent community project. Not sponsored, endorsed, or maintained by AWS.

A deployable governance pattern for AI agents on Amazon Bedrock AgentCore. One command deploys an agent on AgentCore Runtime behind a Gateway with Cedar policy, a decision record in CloudWatch that names the policy behind each allow and deny, and claims stores kept as stores of record.

An evidence pack answers an auditor's questions from the live account (`make evidence`, see [collector/](collector/README.md)).

Bedrock Guardrails in policy screen what a tool returns at the Gateway. Four screens are deployed. The government identifier screen is enforced and withholds a response it matches. The other three record what they would withhold without withholding it. See [docs/guardrail-policies.md](docs/guardrail-policies.md).

Next: a support agent with its own identity and rules, and Agent Registry discovery.

Status: under construction.

## What it proves

Control gaps that block agents in regulated operations, reproduced with synthetic claims data on real infrastructure.

- A claims operations agent reaches a tool that can purge every claim record. The claims stores are protected as stores of record: deletion protection, point-in-time recovery, daily backups and a customer-managed key. None of that stops a purge, and IAM allows it. Cedar policy at the Gateway denies it whatever the model decides, and the CloudWatch trace names the policy that made the decision.
- Two tools read the same claim. `get_claim` returns what an agent needs to answer a status question: status, type, amount, the last four digits of the Social Security number and the birth year. `get_claim_record` returns the whole claim file, with every identifier and health detail in it. It is deliberately not minimized, to show what a guardrail does and does not catch when an API returns too much. Guardrails in policy screen its response at the Gateway. When the government identifier screen matches, the Gateway withholds the whole response, not only the identifier, and the caller gets an error that names the screen. Some of what a claim file holds cannot be screened at all (see Limitations). So the control is the tool that returns only what the caller needs, as `get_claim` does. The screen is the backstop when an API gets that wrong.
- Next: a support agent reads a claim ticket carrying injected instructions. Cedar denies the call the injection asks for.

[docs/controls-map.md](docs/controls-map.md) maps what insurance, financial and AI regulators ask of agents to the control here that produces evidence for each ask, with sources.

## Quickstart

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22 or later, AWS CDK CLI 2.1144 or later, and an AWS account with CloudWatch Transaction Search enabled in us-east-1.

```
scripts/setup.sh
source .venv/bin/activate
make deploy
make seed
make attack SCENARIO=claims-cleanup
make trace
make evidence
make reset
make destroy
```

`make seed` writes 50 synthetic claims to each claims store, and 20 probe records to staging, each carrying one kind of field. Every value is fictional and drawn from ranges that belong to nobody, such as Social Security area 666, which is never assigned. See [`scripts/synthetic.py`](scripts/synthetic.py).

`make deploy` runs five steps in order:

1. `deploy-base`: KMS keys, a trail of every call to the Gateway, network, claims stores, tool Lambda, and the Gateway with its policy engine. A first deploy starts the engine in LOG_ONLY. Later deploys keep the mode it runs in.
2. `discover`: reads tool names from the live Gateway and renders the Cedar files from them.
3. `deploy-policy`: adds the policies to the engine.
4. `enforce`: checks in LOG_ONLY that the policies allow at least one tool, then switches the Gateway to ENFORCE.
5. `deploy-agents`: the agent on AgentCore Runtime, behind its own user pool. The Runtime accepts only tokens issued to the ops console client.

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

Each row is a rule this repo does not meet, and why. `make check` fails if a rule is acknowledged in code and missing here, or listed here and no longer acknowledged.

| Rule | Where | Why it stands |
|---|---|---|
| `AwsSolutions-IAM5` | Tool, Gateway and agent roles | Wildcards the services require: actions without resource-level permissions (including `bedrock:InvokeGuardrailChecks`), CDK asset keys, and names assigned at deploy time. The tool role's purge on every claims table is deliberate: it is the gap the Cedar policy closes. Each one is listed next to its resource. |
| `AwsSolutions-IAM4` | Backup selection roles, deploy-time function | The AWS managed service policy AWS Backup documents for running backups. The basic execution policy on CDK's deploy-time custom resource function. |
| `NIST.800.53.R5-IAMNoInlinePolicy` | Gateway, Runtime, flow log, trail delivery and deploy-time function roles | The constructs write their own grants as inline default policies. Permissions this repo adds are in managed policies. |
| `NIST.800.53.R5-LambdaDLQ` | Tool function, deploy-time function | Both are invoked synchronously. A dead-letter queue receives only failed asynchronous events, so failures go back to the caller and to the logs. |
| `NIST.800.53.R5-LambdaConcurrency` | Deploy-time functions | CDK's custom resource function, once in the Gateway stack to hand the generated client secret to AgentCore Identity, and once in the agents stack to configure the runtime's log group. It runs only during a deploy. The tool function has a concurrency limit. |
| `NIST.800.53.R5-LambdaInsideVPC` | Deploy-time functions | Same functions. They call Cognito and CloudWatch Logs APIs during a deploy. The tool function runs in private subnets. |
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

This is a sandbox pattern. The claims stores are real and their records can be purged. Rows are synthetic. No number in this repo is a production claim.

The ops console is a service that calls the agent with the client-credentials flow. No person signs in in front of it, so a request is tied to the console, not to the person who asked. A production deployment puts user sign-in with MFA in front of the console.

Keys, log groups, user pool and claims stores are removed with the stacks so the sandbox can be torn down. A production deployment retains them, and keeps logs for its audit period instead of 30 days. `make destroy` turns deletion protection off and empties the backup vaults first, on purpose. AgentCore creates the runtime's own log group, so the stacks set its key, masking and retention at deploy time but do not own it, and `make destroy` deletes it last. CDK's deploy-time functions write to log groups the stacks own, with the same key, masking and retention. Any group Lambda created for them earlier, named after its stack, is deleted last as well.

Calls to the Gateway are CloudTrail data events, which no trail records unless asked. This pattern adds its own trail for them, in the same account, with log file validation, its own key, and a copy in CloudWatch Logs. Each event names the tool and the caller's token claims, with arguments and results redacted by the service. Management events stay with the trail the account already has. A production deployment adds the Gateway data events to its organization trail, which delivers to a central log archive account, and keeps the files under Object Lock for its audit period instead of 30 days.

Trace spans in `aws/spans`, where the Gateway's policy decisions land, are encrypted with the AWS owned key and have no data masking. A production deployment sets a customer managed key for X-Ray, which is an account-wide setting. Whether a masking policy can be set on `aws/spans` has not been tested here.

Guardrails in policy have no category for a date of birth or for US health information, such as a medical record number, a diagnosis or an ICD-10 code. Neither can be screened. See [docs/guardrail-policies.md](docs/guardrail-policies.md#what-cannot-be-screened).

Only the government identifier screen is enforced. The contact details, financial and health identifier screens run in LOG_ONLY: they record what they would withhold and withhold nothing.

When a screen withholds a response, the trace shows only the request's ALLOW. The withheld response, and the screen that withheld it, are recorded in the call's CloudTrail event, so the evidence pack reads them from the trail.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.

## Citation

If you use or build on this pattern, cite it with the metadata in `CITATION.cff`
(GitHub's "Cite this repository" button).

## Maintainer

Maintained by Harpreet S. Siddhu.
