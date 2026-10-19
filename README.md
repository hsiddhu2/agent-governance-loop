# agent-governance-loop

Independent community project. Not sponsored, endorsed, or maintained by AWS.

A deployable governance pattern for AI agents on Amazon Bedrock AgentCore. One command deploys a governed two-agent platform with Cedar policy at the Gateway, Bedrock Guardrails in policy, OpenTelemetry tracing to CloudWatch, Agent Registry discovery, and an evidence loop that turns a trace into a regression test.

Status: under construction. Step 1 of 3.

## What it proves

Two control gaps that block agents in regulated operations, reproduced with synthetic claims data on real infrastructure.

- A claims operations agent runs under an IAM role that can delete a claims store. IAM allows the delete. Cedar policy at the Gateway denies it whatever the model decides, and the CloudWatch trace names the policy that made the decision.
- A support agent reads a claim ticket carrying injected instructions and a policyholder record carrying a synthetic identifier. Cedar denies the call the injection asks for. Guardrails in policy withhold the identifier at the Gateway before the tool result reaches the agent.

## Quickstart

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22 or later, AWS CDK CLI 2.1144 or later, and an AWS account with CloudWatch Transaction Search enabled in us-east-1.

```
scripts/setup.sh
source .venv/bin/activate
make deploy
make seed
make attack SCENARIO=claims-cleanup
make trace
make reset
make destroy
```

`make deploy` runs five steps in order:

1. `deploy-base`: tables, tool Lambda, and the Gateway with its policy engine in LOG_ONLY.
2. `discover`: reads tool names from the live Gateway and renders the Cedar files from them.
3. `deploy-policy`: adds the policies to the engine.
4. `enforce`: checks in LOG_ONLY that the policies allow at least one tool, then switches the Gateway to ENFORCE.
5. `deploy-agents`: the agent on AgentCore Runtime.

Enforcement changes only through `make enforce` and `make log-only`. Every other deploy keeps the mode the Gateway already runs in.

To add or rename a tool on a Gateway that already enforces, run `make log-only` first. Under ENFORCE, tools/list hides tools that no policy allows yet.

## Checks

`make check` runs after every change and needs no AWS account:

- `ruff` lint and the offline tests in `tests/`.
- A synth reviewed by the [cdk-nag](https://github.com/cdklabs/cdk-nag) AWS Solutions rule pack. Every finding is either fixed or acknowledged next to the resource with the reason it stands. Template validation issues also fail the synth.
- A synth with no rendered policies, compared with the normal one. Only the policy stack may differ.

Deploys run the same rule pack, so nothing ships without it.

## Limitations

This is a sandbox pattern. Tables are real and the agent can destroy them. Rows are synthetic. No number in this repo is a production claim.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.

## Citation

If you use or build on this pattern, cite it with the metadata in `CITATION.cff`
(GitHub's "Cite this repository" button).

## Maintainer

Maintained by Harpreet S. Siddhu.
