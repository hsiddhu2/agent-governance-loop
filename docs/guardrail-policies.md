# Guardrail policies

Policy in AgentCore accepts two kinds of statement, and they are sent differently.

| Statement | Definition member | Declared with |
|---|---|---|
| Plain `permit` and `forbid` | `cedar` | the CDK `Policy` construct |
| Guardrail conditions (`BedrockGuardrails::...`), the `suppressOutput` effect, temporal conditions | `policy` | `CfnPolicy`, with `definition.policy.statement` |

CreatePolicy takes a `definition` that holds either a `cedar` statement or a `policy` statement ([CreatePolicy](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreatePolicy.html)). The `Policy` construct always writes `cedar`. The AWS sample [sample-native-guardrails-for-bedrock-agentcore](https://github.com/aws-samples/sample-native-guardrails-for-bedrock-agentcore) sends guardrail statements as `policy`, and notes that only that member accepts a `when guardrails` block. Sending one through `cedar` has not been tested here. So the policy stack declares guardrail policies on the resource directly, as the sample does.

## Comments are stripped before a statement is sent

The service rejects a `suppressOutput` statement when `//` comment lines come before the effect, and reports it as an invalid effect: `policy effect must be permit or forbid, found suppressOutput`. The message points at the effect, not at the comments.

The files in `policies/cedar/` keep their comment headers, because those say why each policy exists. At synth time `load_policy_statement` in [`infra/stacks/policy_stack.py`](../infra/stacks/policy_stack.py) drops every line that starts with `//`, drops leading blank lines, and refuses a file whose statement does not then start with `permit`, `forbid` or `suppressOutput`. Line breaks inside the statement are kept. Guardrail policies are sent stripped. Plain Cedar policies are sent as written, since Cedar accepts comments and the live policy then carries its reasons.

## How the policy stack chooses

Each rendered file becomes one policy. A file whose statement calls `BedrockGuardrails::`, uses the `suppressOutput` effect, or has a `temporal` block is declared as a `CfnPolicy` with the `policy` member. Every other file stays on the `Policy` construct.

Two comment lines in a file set how it is created:

- `// validation: IGNORE_ALL_FINDINGS because <reason>`: allowed only on a policy that takes access or output away (`forbid`, `suppressOutput`). The analyzer cannot read a guardrail condition, so the AgentCore guide says to create guardrail policies this way ([Guardrail policy examples](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies-guardrails.html)).
- `// enforcement: LOG_ONLY because <reason>`: the policy records its decisions without applying them ([Test a policy in LOG_ONLY mode](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-test-a-policy.html)). Removing the line, in a reviewed change, applies it.

As a precaution, the policy stack declares a dependency on the Gateway target, so the tool whose output a guardrail policy reads, such as `context.output.policyholder`, exists first. The target is in the Gateway stack, so this is a dependency between stacks. `make deploy` deploys each stack with `--exclusively`, which skips dependencies, so it orders nothing in that path today. A guardrail policy names one action. The schema declares each field the policy reads as a string.

## Writing a sensitive-information screen

On two records tested here, the detector reported every kind of sensitive information it found in the content, whatever categories the call named. A condition such as `.count() > 0` then fires on any personal data at all, and a policy meant for one group of identifiers fires on all of them. So each screen here tests each category it covers by name, `.categories().contains("US_SOCIAL_SECURITY_NUMBER")`, joined with `||`. In one test pair, a screen written this way matched a record carrying its own group and did not match one carrying another group. When an enforced screen fires, the caller's error and the CloudTrail event for the call name it. Each call and its aggregation are kept on one line.

In the decision record, the same detection scores appear once for each `||` term. That suggests each term is its own guardrail call, so a screen with four categories would check the content four times. This is inferred from the repeated scores, not measured. If it holds, a screen with many categories costs more and adds latency to every response it screens.

## Policies are created one at a time

In the account this was built in, policies created or updated together in one engine were refused for naming an action "that does not exist on the target gateway", while each was accepted on its own. The cause is not documented. So the policy stack makes each policy wait for the one before it: permits first, then forbids, then screens.

## What cannot be screened

The policy language accepts a fixed list of sensitive-information categories ([Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html)). Two kinds of data in a life or health claim file have none:

- **Date of birth.** There is no date category. `AGE` is the closest, and a date of birth is not an age.
- **US health information.** The only health identifiers are the Canadian health number and the UK National Health Service number. There is no category for a US medical record number, a health plan member id, a diagnosis, an ICD-10 code or a medication.

A guardrail cannot withhold what it cannot detect. The control for these fields is the tool itself: a tool that returns only what the caller needs, as `get_claim` does, never puts them in the response.

## IAM

The Gateway's service role needs `bedrock:InvokeGuardrailChecks` to run the checks. The Service Authorization Reference lists no resource types for that action, so it is granted on `*`. The checks are defined inside each policy, and there is no guardrail resource to name.
