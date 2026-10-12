# agent-governance-loop

Independent community project. Not sponsored, endorsed, or maintained by AWS.

A deployable governance pattern for AI agents on Amazon Bedrock AgentCore. One command deploys a governed two-agent platform with Cedar policy at the Gateway, Bedrock Guardrails in policy, OpenTelemetry tracing to CloudWatch, Agent Registry discovery, and an evidence loop that turns a trace into a regression test.

Status: under construction. Step 1 of 3.

## What it proves

Two published incidents, reproduced with synthetic data on real infrastructure.

- An operations agent holding an over-scoped IAM role tries to delete a production data store. IAM would allow it. Cedar policy at the Gateway denies it. The CloudWatch trace shows the deny and the policy that made it.
- A support agent reads a ticket containing injected instructions to dump a secrets table. Guardrails catch the blunt version. A paraphrase gets past Guardrails. Cedar denies the query either way.

## Quickstart

Requires Python 3.12, Node 22 or later, AWS CDK CLI 2.1144 or later, and an AWS account with CloudWatch Transaction Search enabled in us-east-1.

```
scripts/setup.sh
source .venv/bin/activate
make deploy
make seed
make attack SCENARIO=pocketos
make trace
make reset
make destroy
```

`make deploy` runs in two halves. The Cedar policy is rendered from the tool names the deployed Gateway reports, so the Gateway must exist before the policy can.

## Limitations

This is a sandbox pattern. Tables are real and the agent can destroy them. Rows are synthetic. No number in this repo is a production claim.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.

## Citation

If you use or build on this pattern, cite it with the metadata in `CITATION.cff`
(GitHub's "Cite this repository" button).

## Maintainer

Maintained by Harpreet S. Siddhu.
