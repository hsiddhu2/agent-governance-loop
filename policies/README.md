# Policies

The rules the Gateway's policy engine applies to every tool call. Each file holds one statement and becomes one policy in the engine, named after the file. A trace that names a determining policy therefore points straight back to a file here.

## The two folders

| Folder | What its files do | Effect |
|---|---|---|
| [`cedar/`](cedar/) | Decide whether a call may run at all | `permit` or `forbid`, plain Cedar |
| [`guardrails/`](guardrails/) | Decide whether a tool's response may reach the caller, by checking it for sensitive data | `suppressOutput` with a guardrail condition |

Default deny applies to everything: a call runs only if a permit allows it and no forbid matches it. A screen runs after the tool, so the tool still runs and reads the data. The screen only withholds the response.

## The files

| File | What it says |
|---|---|
| `cedar/ops_permit_read_tools` | The ops agent may call the four read-only ops tools |
| `cedar/support_permit_tools` | The support agent may read a ticket and look up a claim through the minimized claim tool, nothing else |
| `cedar/ops_forbid_purge` | Nobody may call the purge, in any environment. It names the tool only, so nothing the agent says can change it |
| `guardrails/ops_screen_government_ids` | Withhold the full claim file when it carries a Social Security, taxpayer, passport or driver's licence number |
| `guardrails/ops_screen_contact_details` | The same for names, addresses, ages, phone numbers and email addresses. Records only (LOG_ONLY) |
| `guardrails/ops_screen_financial` | The same for bank account, routing and card numbers. Records only (LOG_ONLY) |
| `guardrails/ops_screen_health_ids` | The same for Canadian health numbers and UK NHS numbers, the only health identifier categories that exist. Records only (LOG_ONLY) |
| `guardrails/support_screen_government_ids` | Withhold a support ticket when a customer pasted a government identifier into it |
| `guardrails/support_screen_financial` | Withhold a support ticket when a customer pasted a bank account, routing or card number into it |

What each screen catches, field by field, is measured in [docs/screen-coverage.md](../docs/screen-coverage.md).

## Templates and rendered files

The committed files are templates, `*.cedar.tmpl`. They never contain a tool name, a Gateway ARN or a client id, because those exist only once the stacks are deployed. They use placeholders instead:

| Placeholder | Filled with |
|---|---|
| `{{TOOL:get_claim}}` | The tool's name as the Gateway lists it. The Gateway prefixes each tool with its target's name, and the prefix format is read, never typed |
| `{{GATEWAY_ARN}}` | The Gateway's ARN. Every statement names the Gateway it applies to |
| `{{PRINCIPAL:ops_agent}}` | The agent's Gateway client id, which is its Cedar principal |

`make discover` reads the live Gateway and writes `tool_names.json` and `gateway.json` in this folder, then renders each template next to itself as a `.cedar` file. The rendered files and the two JSON files are not committed. Rendering stops without writing anything if a placeholder cannot be filled, and removes any rendered file whose template is gone, so a deleted rule cannot keep enforcing.

## Lines the build reads

Two comment lines change how a policy is created. Each must give its reason after `because`, and the build fails if it does not.

- `// enforcement: LOG_ONLY because <reason>` creates the policy in LOG_ONLY: it records what it would decide and applies nothing. Every other policy is ACTIVE. Removing the line, in a reviewed change, turns the policy on.
- `// validation: IGNORE_ALL_FINDINGS because <reason>` skips the policy analyzer's semantic checks. Only a forbid or a screen may do this, because neither can grant anything. Every other policy is created with `FAIL_ON_ANY_FINDINGS`.

## How they reach the engine

The policy stack creates one policy per rendered file, one at a time: permits first, then forbids, then screens. Creating several policies in one engine at once was refused in testing. Screens are created in the API's `policy` member, not `cedar`, and without their comment lines, because the service rejects comments before a `suppressOutput` effect. See [docs/guardrail-policies.md](../docs/guardrail-policies.md).

To add or rename a tool, run `make log-only` first: under ENFORCE, discovery cannot see a tool that no policy allows yet.
