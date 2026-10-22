# agentcore-evidence

An evidence pack for agents behind an Amazon Bedrock AgentCore Gateway, read from the live account.

An auditor asks what the agents do in production. This answers with files: what exists, who each caller is, what policy allows, whether it is enforced, every decision with the policy that made it, every call with the caller's token subject, every configuration change, and how each record is kept. A summary maps each finding to what regulators and standards bodies ask, with the source quoted.

It runs against any account with an AgentCore Gateway. It does not need this repo's stacks.

## Install and run

```
pip install -e collector
agentcore-evidence collect --gateway <name or id> --region us-east-1 --since 24h --out ./evidence/run1
```

`--redact` replaces account ids, client ids, user pool ids, email addresses, IP addresses and sign-in session names with stable placeholders, so a pack can leave the account. `--controls <file>` maps findings to your own controls instead of the bundled `controls.yaml`. `--profile` picks the AWS profile.

The output directory must be empty or new, so no file from an earlier run mixes in.

A redacted pack from this repo's own deployment is in [`evidence/examples/agl-gateway/`](../evidence/examples/agl-gateway/summary.md). Start with `summary.md`. With `--redact`, times are offsets from the start of the window, such as `T+23:46:38`.

## Permissions

Every call is a read. [`iam-policy.json`](iam-policy.json) lists them. Two choices keep the collector from ever holding a secret:

- Caller identity comes from the authorizer configuration on the Gateway and each runtime, never from the identity provider. A Cognito client description includes the client secret.
- Runtime environment variables are read by `GetAgentRuntime` but never written to the pack.

## The pack

| File | Question | Source |
|---|---|---|
| `inventory.json` | What agents and tools exist? | Gateway, its targets, and the runtimes in the Region |
| `identity.json` | Who may call the Gateway and each runtime? | Their JWT authorizer configuration |
| `policies.json`, `policies/*.cedar` | What may each caller do? | Every policy in the Gateway's engine, with a SHA-256 of each statement |
| `enforcement.json` | Is policy enforced? | The Gateway's engine mode and each policy's own mode. Either can record without applying |
| `decisions.json` | What did the agents do? | Policy spans in `aws/spans`, joined to the tool span by request id for the tool name |
| `callers.json` | Who made each call? | A CloudTrail trail that records Gateway data events and sends them to CloudWatch Logs |
| `changes.json` | What changed, and who changed it? | CloudTrail management events for AgentCore configuration calls |
| `retention.json` | Is the record protected? | Key, retention and masking of each log group, and file validation of each trail |
| `checks.json`, `summary.md` | Does the evidence support each ask? | The checks below, against `controls.yaml` |
| `manifest.json` | Was the pack changed after it was written? | SHA-256 of every file, the window, the caller, the tool version |

## Statuses

- **PASS**: the evidence shows the control working.
- **FAIL**: the evidence shows it is not.
- **GAP**: the evidence needed is not there, so nothing can be said. A Gateway with no trail recording its data events is a GAP for callers, not a PASS.

A control takes the status of its weakest check. A PASS supports an ask. It does not satisfy it: every source asks for more than an account can show, and compliance is decided over a whole program.

## Limits

- One Gateway per run, in one Region.
- Tool arguments and results are never collected. The spans do not carry them and CloudTrail redacts them.
- Trails that deliver only to S3 show as a GAP for callers. This version reads trails sent to CloudWatch Logs.
- Logs Insights returns at most 10,000 rows per query, so a busy Gateway needs a shorter window.
- Spans name the policy behind a decision, not the caller. The caller comes from CloudTrail.
