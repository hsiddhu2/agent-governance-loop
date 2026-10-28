# Controls map

What regulators and standards bodies ask of AI systems that act, and where this pattern produces evidence for each ask.

This page maps asks to controls. It is not legal advice and does not make a deployment compliant with anything. Compliance is decided by an examiner or auditor over a whole program, and the same documents ask for much that no gateway can provide (see [What this does not cover](#what-this-does-not-cover)). None of the documents below name AgentCore, Cedar or a gateway. The mapping is this project's reading.

Quotes are short and verbatim. Follow the link for context.

## Status key

- **Built**: deployed by `make deploy` and shown working in this repo.
- **Partial**: built, with a stated limit.
- **Planned**: in progress, not yet in the repo.
- The evidence pack uses a different scale. Its PASS says the checks it runs passed in the account. A Partial control can PASS there, and the pack's Limits column states the part it cannot show.

## The loop

| Control | What it does here | Status |
|---|---|---|
| Catalog | Lists the agents and tools that exist, separate from what each may do. An Agent Registry records each agent and the Gateway's tools, and a record is approved only when it matches what is deployed | Built |
| Identity | Two agents. Each has its own client and token. Each Runtime accepts only its caller's client, and the Gateway sees each agent as its own Cedar principal | Built |
| Enforce | Cedar policy at the Gateway. Default deny, an explicit forbid on the destructive tool | Built |
| Filter | Bedrock Guardrails in policy screen what a tool returns to the agent. Four screens on the full claim file, one enforced and three recording only. Two on support tickets, both enforced | Partial: date of birth and US health information cannot be screened |
| Trace | Each allow and deny is recorded in the trace. A deny by a forbid names that forbid, and a default deny names no policy. A withheld response is recorded in CloudTrail with the screen that withheld it. Log groups the stacks own are encrypted with a customer managed key, masked and retained. `aws/spans` has no customer managed key and no data masking | Built |
| Change control | Policy as code. A first deploy starts the engine in LOG_ONLY. A screen can carry its own LOG_ONLY line, so it records before it withholds. Enforcement changes only through one make target | Built |
| Stop | A policy-level stop: a forbid denies every call to a tool at the Gateway, whatever the model decides | Partial: no approval step for individual actions |

## Asks and where the evidence comes from

| Ask | Sources | Control | Evidence in this repo |
|---|---|---|---|
| Keep an inventory of AI systems | NAIC Model Bulletin, Sec 3 item 3.3(a): "Inventories and descriptions of the Predictive Models." MAS AI Risk Management Guidelines 4.5: "an accurate inventory of AI use cases, systems or models". NIST AI RMF GOVERN 1.6 | Catalog | The Agent Registry catalog (`make approve-catalog`), and the evidence pack's check that the Gateway and every runtime are named in an approved record |
| Limit access to least privilege | MAS 5.22(a): "access controls based on the principle of least privilege." NAIC Model Bulletin, Sec 3 item 3.5: "unauthorized access to the Predictive Models themselves." | Identity, Enforce | One client per agent. Each Runtime accepts only a Cognito token from its own console client, with that agent's invoke scope (`infra/stacks/agents_stack.py`) |
| Limit what an agent can do | FINRA annual oversight report, agents section: agents "may act beyond the user’s actual or intended scope and authority", and firms consider "guardrails or control mechanisms to limit or restrict agent behaviors, actions or decisions." NAIC Model Bulletin, Sec 3 item 3.1: "constraints and controls on automation" | Enforce | `policies/cedar/`, default deny, `ops_forbid_purge`, a direct call refused with the policy named, each agent checked against each tool (`make matrix`) |
| Keep sensitive data from leaving | FINRA: agents "may unintentionally store, explore, disclose or misuse sensitive or proprietary information." | Filter | Partial: `ops_screen_government_ids` withholds a claim file carrying a Social Security number, and the ticket screens withhold a ticket carrying one or a card number. The caller's error and the CloudTrail event name the screen. Three claim-file screens record only. Date of birth and US health information cannot be screened ([screen coverage](screen-coverage.md)). `get_claim` returns the birth year, the last four digits of the Social Security number and no health detail |
| Record events automatically and track tools used | EU AI Act Art. 12(1): "automatic recording of events (logs) over the lifetime of the system." MAS 5.23(a): "actions taken, tools used should also be monitored." NIST AI RMF MEASURE 2.4 | Trace | Decision spans in `aws/spans` naming the determining policy (`make trace`). Withheld responses in the call's CloudTrail event, naming the screen |
| Keep logs for a set period | EU AI Act Art. 26(6): logs kept for "at least six months". NAIC Model Bulletin, Sec 3 item 3.6: "Data and record retention." | Trace | The stacks' own log groups have a customer managed key, masking and a retention setting. `aws/spans` has no customer managed key and no data masking. In the sample pack its retention was 30 days. The sandbox keeps 30 days, and production sets its audit period (see [design-review.md](design-review.md#everything-is-deleted-on-teardown)) |
| Control changes | MAS 5.25(b): "change control mechanisms (with appropriate human oversight) to prevent unauthorised alterations". NIST AI RMF MANAGE 4.1 | Change control | Cedar in version control, a LOG_ONLY line on a screen before it withholds, `make enforce` and `make log-only` as the only mode changes, a type-change guard before every deploy |
| Be able to stop the system | EU AI Act Art. 14(4)(e): "a ‘stop’ button or a similar procedure that allows the system to come to a halt in a safe state." MAS 5.23(b): "kill switches" or override mechanisms. NIST AI 600-1 GV-1.7-001 | Stop | Partial: a forbid stops a tool for every agent at the Gateway. No stop inside the agent and no approval step |

## The insurance view

Remarks to the NAIC Big Data and Artificial Intelligence (H) Working Group, recorded in its meeting minutes (pending adoption), listed what evidence for agentic AI should show:

| In the minutes | Control | Status |
|---|---|---|
| "whether permissions are tested" | Enforce, Identity | Built |
| "whether actions are logged for company reconstruction" | Trace | Built |
| "whether there is a kill switch to roll the process back to a safe state" | Stop | Partial |
| "whether a person has the authority to override actions" | Stop | Partial |

The same remarks said "Policy alone is not enough". The point of this repo is the operational part.

## What this does not cover

These are asked for in the same documents and are outside a gateway's reach:

- Bias and unfair-discrimination testing, data lineage and quality.
- Model validation and drift monitoring.
- Notice to consumers or workers that AI is in use.
- Third-party due diligence and contract audit rights.
- Board and senior-management accountability, committees and training.
- Incident reporting to authorities.
- Human approval of individual consequential actions.
- Deciding whether a use is high-risk under the EU AI Act, and writing the governance program itself.

## Sources

- NAIC, Model Bulletin: Use of Artificial Intelligence Systems by Insurers. https://content.naic.org/sites/default/files/2023-12-4%252520Model%252520Bulletin_Adopted_0.pdf
- NAIC, adoption map for the Model Bulletin. https://content.naic.org/sites/default/files/legal-adoption-map-ai-model-bulletin.pdf
- NAIC Big Data and Artificial Intelligence (H) Working Group, meeting minutes. https://content.naic.org/sites/default/files/call_materials/minutes-bdaiwg081326-final.pdf
- Monetary Authority of Singapore, Guidelines on Artificial Intelligence Risk Management. https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf
- Regulation (EU) 2024/1689 (AI Act). https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689
- FINRA, Annual Regulatory Oversight Report, GenAI section. https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai
- NIST AI 100-1, AI Risk Management Framework. https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf
- NIST AI 600-1, Generative AI Profile. https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
