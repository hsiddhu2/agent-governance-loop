# Guardrail policies

Policy in AgentCore accepts two kinds of statement, and they are sent differently.

| Statement | Definition member | Declared with |
|---|---|---|
| Plain `permit` and `forbid` | `cedar` | the CDK `Policy` construct |
| Guardrail conditions (`BedrockGuardrails::...`), the `suppressOutput` effect, temporal conditions | `policy` | `CfnPolicy`, with `definition.policy.statement` |

CreatePolicy takes a `definition` that holds either a `cedar` statement or a `policy` statement ([CreatePolicy](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreatePolicy.html)). The `Policy` construct always writes `cedar`, and a guardrail statement sent that way is rejected as unparseable. So the policy stack declares guardrail policies on the resource directly.

## Comments are stripped before a statement is sent

The service rejects a `suppressOutput` statement when `//` comment lines come before the effect, and reports it as an invalid effect: `policy effect must be permit or forbid, found suppressOutput`. The message points at the effect, not at the comments.

The files in `policies/cedar/` keep their comment headers, because those say why each policy exists. At synth time `load_policy_statement` in [`infra/stacks/policy_stack.py`](../infra/stacks/policy_stack.py) drops every line that starts with `//`, drops leading blank lines, and refuses a file whose statement does not then start with `permit`, `forbid` or `suppressOutput`. Line breaks inside the statement are kept. Guardrail policies are sent stripped. Plain Cedar policies are sent as written, since Cedar accepts comments and the live policy then carries its reasons.

## How the policy stack chooses

Each rendered file becomes one policy. A file whose statement calls `BedrockGuardrails::`, uses the `suppressOutput` effect, or has a `temporal` block is declared as a `CfnPolicy` with the `policy` member. Every other file stays on the `Policy` construct.

Two comment lines in a file set how it is created:

- `// validation: IGNORE_ALL_FINDINGS because <reason>`: allowed only on a policy that takes access or output away (`forbid`, `suppressOutput`). The analyzer cannot read a guardrail condition, so the AgentCore guide says to create guardrail policies this way ([Guardrail policy examples](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies-guardrails.html)).
- `// enforcement: LOG_ONLY because <reason>`: the policy records its decisions without applying them ([Test a policy in LOG_ONLY mode](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-test-a-policy.html)). Removing the line, in a reviewed change, applies it.

Each guardrail policy depends on the Gateway target, because its data path, such as `context.output.policyholder`, is checked against the tool's output schema. A guardrail policy names one action. The schema declares each field the policy reads as a string.

## Writing a sensitive-information screen

The detector reports every kind of sensitive information it finds in the content, whatever categories the call names. A condition such as `.count() > 0` therefore fires on any personal data at all, and a policy meant for one group of identifiers fires on all of them. Each screen here tests each category it covers by name, `.categories().contains("US_SOCIAL_SECURITY_NUMBER")`, joined with `||`, so the decision record names the group that actually matched. Each call and its aggregation are kept on one line.

Each `||` term is its own guardrail call, so a screen with four categories checks the content four times. A screen that needs many categories costs more, and adds latency to every response it screens.

## What cannot be screened

The policy language accepts a fixed list of sensitive-information categories ([Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html)). Two kinds of data in a life or health claim file have none:

- **Date of birth.** There is no date category. `AGE` is the closest, and a date of birth is not an age.
- **US health information.** The only health identifiers are the Canadian health number and the UK National Health Service number. There is no category for a US medical record number, a health plan member id, a diagnosis, an ICD-10 code or a medication.

A guardrail cannot withhold what it cannot detect. The control for these fields is the tool itself: a tool that returns only what the caller needs, as `get_claim` does, never puts them in the response.

## IAM

The Gateway's service role needs `bedrock:InvokeGuardrailChecks` to run the checks. The Service Authorization Reference lists no resource types for that action, so it is granted on `*`. The checks are defined inside each policy, and there is no guardrail resource to name.
