# Known gaps, in plain terms

This pattern runs in a sandbox account. Automated rule checks review every resource it creates, and a few rules are not met. The README lists them in a short table. This page explains each one so that anyone can follow it, with or without AWS experience.

Every gap falls into one of three kinds:

- **Blocked by AWS or by the CDK.** The pattern cannot meet the rule today. An AWS service or the CDK library does not offer a way.
- **The rule does not fit.** The rule was written for a different situation from this one.
- **Our choice for a sandbox.** The pattern could meet the rule, but a sandbox in one account does not need it. A production team should change it, and each entry says how.

## Where the rules come from

Every `make check` and every deploy runs three sets of automated rules over the templates. A finding stops the build unless the code accepts it with a written reason. The README table lists every accepted finding, and `make check` fails if the table and the code disagree.

| Rule ids | Source |
|---|---|
| `AwsSolutions-*` | [cdk-nag](https://github.com/cdklabs/cdk-nag), the AWS Solutions rule pack ([rule list](https://github.com/cdklabs/cdk-nag/blob/main/RULES.md)) |
| `NIST.800.53.R5-*` | cdk-nag, rules mapped to [NIST SP 800-53 Rev 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final), a published catalog of security and privacy controls |
| `F3002`, `F3003`, `W3010` | The CloudFormation template validation that runs when the CDK builds the templates |

Some gaps are not rule findings. They are things the pattern does not do, listed at the end of the README. They are explained here too.

## Summary

| Gap | Kind | In one line |
|---|---|---|
| [Some permissions use a wildcard](#some-permissions-use-a-wildcard) | Blocked by AWS or the CDK, one part on purpose | Some AWS actions cannot be limited to one resource, and some names are not known until deploy time |
| [Two AWS managed policies](#two-aws-managed-policies) | Blocked by AWS or the CDK | AWS Backup and the CDK attach them |
| [Inline policies on some roles](#inline-policies-on-some-roles) | Blocked by the CDK | The CDK writes its own grants that way |
| [No concurrency limit on deploy-time functions](#no-concurrency-limit-on-deploy-time-functions) | Blocked by the CDK | The CDK offers no setting for it |
| [Template validation findings](#template-validation-findings) | Blocked by the CDK | The CDK's copy of the template schema is older than the live one |
| [The Gateway role's trust policy is replaced](#the-gateway-roles-trust-policy-is-replaced) | Blocked by the CDK, worked around | The CDK's default lets any Gateway use the role |
| [Some data cannot be screened](#some-data-cannot-be-screened) | Blocked by AWS | No guardrail category exists for a date of birth or health information |
| [A withheld response is not in the trace](#a-withheld-response-is-not-in-the-trace) | Blocked by AWS | The trace records the request, not the withhold |
| [No dead-letter queue on functions](#no-dead-letter-queue-on-functions) | The rule does not fit | The functions are never called in the way a dead-letter queue serves |
| [No passwords, MFA or sign-in protection on user pools](#no-passwords-mfa-or-sign-in-protection-on-user-pools) | The rule does not fit | No person signs in to these pools |
| [The tool role can purge every claims store](#the-tool-role-can-purge-every-claims-store) | Our choice, on purpose | It is the gap the policy closes |
| [The trail bucket has no access logs or copy](#the-trail-bucket-has-no-access-logs-or-copy) | Our choice for a sandbox | A production trail goes to a separate log archive account |
| [Deploy-time functions run outside the network](#deploy-time-functions-run-outside-the-network) | Our choice for a sandbox | Moving them in needs private endpoints that cost money every hour |
| [Trace data uses the AWS owned key](#trace-data-uses-the-aws-owned-key) | Our choice for a sandbox | The setting applies to the whole account |
| [The trail stays in the same account](#the-trail-stays-in-the-same-account) | Our choice for a sandbox | A production trail goes to a separate log archive account |
| [Everything is deleted on teardown](#everything-is-deleted-on-teardown) | Our choice for a sandbox | So the sandbox can be removed completely |
| [No person signs in to the console](#no-person-signs-in-to-the-console) | Our choice for a sandbox | A request is tied to the console, not to a person |
| [Three claim-file screens only record](#three-claim-file-screens-only-record) | Our choice, for now | Each screen is measured before it withholds anything |
| [Catalog approval is automated](#catalog-approval-is-automated) | Our choice for a sandbox | A script approves records, not a person |

## Blocked by AWS or the CDK

### Some permissions use a wildcard

Rule: `AwsSolutions-IAM5`. It asks that every permission name the exact resource it applies to.

What happens here: some permissions say `*`, which means any resource, or end in a `*` after a name.

Why, with examples:

- Some AWS actions cannot be limited to one resource. The AWS service itself does not allow it. Examples: `bedrock:InvokeGuardrailChecks`, which runs the guardrail screens, `dynamodb:ListTables`, which `list_env` uses, writing traces to X-Ray, and sending metrics to CloudWatch.
- Some names are not known until AWS creates the resource. Examples: the runtime's id, which its log group and its identity are named after, the random suffix Secrets Manager adds to a secret's name, and the log stream names Lambda picks while it runs. The permission names everything up to the unknown part, then `*`.
- Some files are stored under a name made from their content. The CDK stores the agent's code and the tool schema in its asset bucket under such a name.

What blocks a fix: the services and the CDK. Each wildcard is listed in the code next to the resource it is on, with its reason.

One wildcard is on purpose. See [The tool role can purge every claims store](#the-tool-role-can-purge-every-claims-store).

### Two AWS managed policies

Rule: `AwsSolutions-IAM4`. It asks that roles use policies you write, not policies AWS writes.

What happens here: two roles use a policy AWS maintains.

Why:

- AWS Backup's role uses `AWSBackupServiceRolePolicyForBackup`. This is the policy AWS Backup documents for running backups, and AWS updates it as Backup supports new kinds of resources.
- The CDK's deploy-time function uses `AWSLambdaBasicExecutionRole`, which lets it write its own logs. The CDK attaches it.

What blocks a fix: writing these by hand means tracking every change AWS makes to them. The AWS version is the safer choice.

### Inline policies on some roles

Rule: `NIST.800.53.R5-IAMNoInlinePolicy`. It asks that permissions live in separate policies that can be reviewed and reused, not inside a role.

What happens here: the roles the CDK builds for the Gateway, the runtimes, the flow log, the trail and the deploy-time functions carry their grants inside the role.

Why: that is how the CDK writes the grants it adds itself. Every permission this pattern adds is in a separate, managed policy.

What blocks a fix: the CDK. The inline grants are small and each is scoped, as the code notes at each one.

### No concurrency limit on deploy-time functions

Rule: `NIST.800.53.R5-LambdaConcurrency`. It asks that each function have a limit on how many copies run at once.

What happens here: two short functions that the CDK provides run during a deploy. One hands the Gateway's client secret to AgentCore Identity. The other sets the key, masking and retention on each runtime's log group. They have no limit.

Why: the CDK construct behind them, `AwsCustomResource`, has no setting for it. They run only while CloudFormation deploys a stack. The tool functions, which run all the time, do have a limit of 5.

What blocks a fix: the CDK.

### Template validation findings

Rules: `F3002`, `F3003`, `W3010`. They come from the check that a template matches CloudFormation's published description of each resource type.

What happens here: three findings. Two are on the network's flow log and its availability zones. The CDK library acknowledges those itself. The third is on the catalog: the setting that encrypts it with this pattern's own key.

Why: the CDK carries a copy of CloudFormation's resource descriptions, and its copy is older than the live one. The live description has the catalog's encryption setting, and a deploy is checked against the live one, so the setting works.

What blocks a fix: a newer CDK release that updates its copy.

### The Gateway role's trust policy is replaced

This is not a rule finding. It is listed in the README's Limitations.

What happens: the role the Gateway uses to call the tools trusts the AgentCore service. In its default form, the CDK construct adds a second statement with no condition, so any Gateway in the account can use the role. This was tested: a second Gateway, with a name outside this pattern, called a tool with this role.

What the pattern does: it replaces the trust policy with the single statement that names this Gateway. After the change the same test was refused.

What blocks a clean fix: the CDK. The problem is [aws-cdk#38780](https://github.com/aws/aws-cdk/issues/38780). Remove the replacement once the construct is fixed.

### Some data cannot be screened

What happens: a claim file holds a date of birth, a medical record number, a diagnosis and an ICD-10 code. None of them can be screened.

Why: a screen uses the categories Bedrock Guardrails can detect, and none exists for these. The full list of fields and results is in [screen-coverage.md](screen-coverage.md).

What blocks a fix: AWS. Until a category exists, keep these fields out of tool output, in the tool's own code.

### A withheld response is not in the trace

What happens: when a screen withholds a response, the trace shows only that the request was allowed. It does not show the withhold or which screen did it.

Where it is recorded: the caller's error names the screen, and so does the call's CloudTrail event. The evidence pack reads withholds from CloudTrail for this reason.

What blocks a fix: AWS. A dashboard built only on trace decisions will undercount withholds.

## The rule does not fit

### No dead-letter queue on functions

Rule: `NIST.800.53.R5-LambdaDLQ`. It asks that each function have a queue that keeps events which failed.

Why it does not fit: a dead-letter queue keeps only events from calls where the caller does not wait for an answer. Every function here is called by something that waits: the Gateway calls the tools, and CloudFormation calls the deploy-time functions. A failure goes straight back to the caller and into the function's logs. A queue would never receive anything.

### No passwords, MFA or sign-in protection on user pools

Rules: `AwsSolutions-COG1`, `COG2`, `COG8`. They ask for a password policy, multi-factor sign-in and protection against risky sign-ins.

Why they do not fit: no person signs in to these pools. Their only clients are services that get a token with a client id and secret, the OAuth client-credentials flow. There is no password to protect.

For the person who uses the console, see [No person signs in to the console](#no-person-signs-in-to-the-console).

## Our choices

### The tool role can purge every claims store

Rule: `AwsSolutions-IAM5`, one of its findings.

What happens: the ops tool function is allowed to delete every row in every claims store.

Why: this is the point of the pattern. Tool permissions are often broader than any one agent should use. The Cedar policy at the Gateway is what stops the ops agent from calling the purge, and the access test shows it doing so. With a narrow role there would be nothing for the policy to prove.

In production: give each tool role only what its tools need, and keep the Gateway policy as a second, independent control. The support tool role here is already narrow: it can read one ticket.

### The trail bucket has no access logs or copy

Rules: `AwsSolutions-S1`, `NIST.800.53.R5-S3BucketLoggingEnabled`, `NIST.800.53.R5-S3BucketReplicationEnabled`. They ask that a bucket log who reads it and keep a copy in another place.

What happens: the bucket for the Gateway call trail has neither.

Why: only CloudTrail writes to it, and reads of it are already recorded by the account's own trail. A sandbox has one account, so there is nowhere separate to copy to.

In production: send the Gateway's data events to the organization trail. It delivers to a separate log archive account, which keeps its own access logs and copies.

### Deploy-time functions run outside the network

Rule: `NIST.800.53.R5-LambdaInsideVPC`. It asks that functions run inside a private network.

What happens: the two deploy-time functions run outside the network. The tool functions run inside it, in private subnets with no route to the internet.

Why: inside the network, the functions would need private routes to the AWS services they call. Those are Cognito and CloudWatch Logs, plus S3, where CloudFormation collects each function's answer. Cognito and CloudWatch Logs need interface endpoints, which charge for every hour they exist in every availability zone, plus a charge per GB ([pricing](https://aws.amazon.com/privatelink/pricing/)). The functions run for a few seconds per deploy.

This is a choice, not a limit: `AwsCustomResource` accepts a network setting.

In production: if the account requires every function inside a network, add interface endpoints for Cognito and CloudWatch Logs and a gateway endpoint for S3, then give the deploy-time functions the private subnets.

### Trace data uses the AWS owned key

This is not a rule finding. The evidence pack reports it as a failed check.

What happens: trace data in `aws/spans`, where the Gateway's policy decisions land, is encrypted with a key AWS owns and manages, and has no data masking.

Why: the setting for a customer managed key covers X-Ray for the whole account, not one application. A sandbox pattern does not change account-wide settings. Whether masking can be set on `aws/spans` has not been tested.

In production: set a customer managed key for X-Ray as part of the account baseline.

### The trail stays in the same account

What happens: the pattern adds its own trail for calls to the Gateway, in the same account. It has log file validation, its own key and a copy in CloudWatch Logs.

Why: AWS records calls to the Gateway only when a trail asks for them, and a sandbox has no organization trail to add them to.

In production: add the Gateway's data events to the organization trail, which delivers to a log archive account, and keep the files locked against deletion for the audit period.

### Everything is deleted on teardown

What happens: `make destroy` removes keys, logs, user pools and claims stores. It turns off deletion protection and empties the backup vaults first. Logs are kept for 30 days.

Why: so the sandbox can be removed completely, with nothing left that costs money.

In production: keep these resources when a stack is removed, and keep logs for as long as the audit period requires.

### No person signs in to the console

What happens: the ops console calls the agent as a service, with a client id and secret. No person signs in in front of it. So a request is tied to the console, not to the person who asked.

Why: the pattern shows the governance between the agent and its tools. Who may use the console is a separate control.

In production: put user sign-in with MFA in front of the console, and pass the person's identity through to the agent.

### Three claim-file screens only record

What happens: four screens read the full claim file. The government identifier screen withholds. The contact details, financial and health identifier screens run in LOG_ONLY: they record what they would have withheld, and withhold nothing.

Why: each screen is measured before it is allowed to block anything. The measurements are in [screen-coverage.md](screen-coverage.md).

In production: switch each screen to withhold once its measurements show it catches what it should and nothing it should not.

### Catalog approval is automated

What happens: `make approve-catalog` approves each catalog record once it matches what is deployed. A script does the review.

Why: in a sandbox there is no second person to review.

In production: run the approval under a role that can change a record's status and cannot publish one, or have a person approve.
