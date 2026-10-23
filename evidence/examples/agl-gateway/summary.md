# Evidence pack

Gateway `agl-gateway` in us-east-1. Window T+00:00:00 to T+23:59:59.
Collected T+1d 00:00:10 by `arn:aws:sts::<account-1>:assumed-role/AWSReservedSSO_AdministratorAccess_<sso-role-1>/<session-2>`.
19 decisions but 17 recorded calls. The trail's first recorded event, T+15:25:48, is later than the earliest decision, T+10:56:05, so earlier decisions have no matching call.

This pack supports evidence for the asks below. It does not show compliance with any of them: each source asks for more than an account can show, and compliance is decided over a whole program.

PASS: the evidence shows the control working. FAIL: it shows the control is not. GAP: the evidence needed is not there.

## Controls

| Ask | Status | Checks | Limits |
|---|---|---|---|
| Keep an inventory of AI systems | **PASS** | inventory.gateway_listed | Covers what sits behind this Gateway and the runtimes in this Region, not agents elsewhere. |
| Limit access to least privilege | **PASS** | identity.gateway_jwt, identity.runtimes_jwt, policies.engine_attached |  |
| Limit what an agent can do | **PASS** | policies.engine_attached, policies.forbid_present, enforcement.enforced, decisions.deny_names_policy |  |
| Record events automatically and track tools used | **PASS** | decisions.recorded, callers.recorded, callers.identified |  |
| Keep logs for a set period, protected | **FAIL** | retention.logs_encrypted, retention.logs_bounded, retention.logs_masked, retention.trail_validated | Shows a retention period is set, not that it meets the period a regulation requires. |
| Control changes | **PASS** | changes.recorded | Shows who changed what. Whether each change was reviewed lives in your change process. |
| Be able to stop the system | **PASS** | policies.forbid_present, enforcement.enforced | A forbid stops a tool at the Gateway for every caller. It is not an approval step for single actions. |
| Evidence for agentic AI, as listed in remarks to the NAIC Big Data and AI (H) Working Group (minutes pending adoption) | **PASS** | decisions.deny_names_policy, callers.recorded, callers.identified, enforcement.enforced | The same remarks ask about a kill switch and a person's authority to override. See the stop control. |

## Checks

| Check | Status | Finding | Evidence |
|---|---|---|---|
| inventory.gateway_listed | PASS | 1 target(s) on the Gateway, 1 runtime(s) | `inventory.json` |
| identity.gateway_jwt | PASS | JWT inbound, 1 allowed client(s) | `identity.json` |
| identity.runtimes_jwt | PASS | 1 runtime(s), each accepting named clients only | `identity.json` |
| policies.engine_attached | PASS | engine agl_engine-mmk18ak0rd | `policies.json` |
| policies.forbid_present | PASS | active forbid: ops_forbid_purge | `policies.json` |
| enforcement.enforced | PASS | Gateway mode ENFORCE, 2 permit and forbid policies ACTIVE. Screens, judged apart: ops_screen_contact_details LOG_ONLY, ops_screen_financial LOG_ONLY, ops_screen_government_ids ACTIVE, ops_screen_health_ids LOG_ONLY | `enforcement.json` |
| decisions.recorded | PASS | ALLOW 11, DENY 4, SUPPRESSED 4 | `decisions.json` |
| decisions.deny_names_policy | PASS | 4 deny(s) naming ops_forbid_purge-zlncpdalfy | `decisions.json` |
| callers.recorded | PASS | 17 call(s) in trail agl-gateway-tool-calls | `callers.json` |
| callers.identified | PASS | every call names its token subject (1 distinct) | `callers.json` |
| callers.suppression_names_policy | PASS | 4 response(s) withheld, naming ops_screen_government_ids-1ylf7yzw40 | `callers.json` |
| changes.recorded | PASS | 86 control-plane write(s) in the window | `changes.json` |
| retention.logs_encrypted | FAIL | no customer managed key: aws/spans | `retention.json` |
| retention.logs_bounded | PASS | 3 log group(s) | `retention.json` |
| retention.logs_masked | FAIL | no data masking: aws/spans | `retention.json` |
| retention.trail_validated | PASS | log file validation on | `retention.json` |

## Sources

- Keep an inventory of AI systems: NAIC Model Bulletin, Sec 3, 3.3(a): "Inventories and descriptions of the Predictive Models." https://content.naic.org/sites/default/files/2023-12-4%252520Model%252520Bulletin_Adopted_0.pdf
- Keep an inventory of AI systems: MAS Guidelines on AI Risk Management, 4.5: "an accurate inventory of AI use cases, systems or models" https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf
- Limit access to least privilege: MAS Guidelines on AI Risk Management, 5.22(a): "access controls based on the principle of least privilege." https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf
- Limit access to least privilege: NAIC Model Bulletin, Sec 3, 3.5: "unauthorized access to the Predictive Models themselves." https://content.naic.org/sites/default/files/2023-12-4%252520Model%252520Bulletin_Adopted_0.pdf
- Limit what an agent can do: FINRA Annual Regulatory Oversight Report, GenAI section, AI agents: "guardrails or control mechanisms to limit or restrict agent behaviors, actions or decisions." https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai
- Limit what an agent can do: NAIC Model Bulletin, Sec 3, 3.1: "constraints and controls on automation" https://content.naic.org/sites/default/files/2023-12-4%252520Model%252520Bulletin_Adopted_0.pdf
- Record events automatically and track tools used: EU AI Act, Art. 12(1): "automatic recording of events (logs) over the lifetime of the system." https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689
- Record events automatically and track tools used: MAS Guidelines on AI Risk Management, 5.23(a): "actions taken, tools used should also be monitored." https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf
- Keep logs for a set period, protected: EU AI Act, Art. 26(6): "at least six months" https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689
- Keep logs for a set period, protected: NAIC Model Bulletin, Sec 3, 3.6: "Data and record retention." https://content.naic.org/sites/default/files/2023-12-4%252520Model%252520Bulletin_Adopted_0.pdf
- Control changes: MAS Guidelines on AI Risk Management, 5.25(b): "change control mechanisms (with appropriate human oversight) to prevent unauthorised alterations" https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf
- Be able to stop the system: EU AI Act, Art. 14(4)(e): "a stop button or a similar procedure that allows the system to come to a halt in a safe state." https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=OJ:L_202401689
- Be able to stop the system: MAS Guidelines on AI Risk Management, 5.23(b): "kill switches" https://www.mas.gov.sg/-/media/mas-media-library/regulation/guidelines/bd/guidelines-on-artificial-intelligence-risk-management-for-financial-institutions/guidelines-on-artificial-intelligence-risk-management.pdf
- Evidence for agentic AI, as listed in remarks to the NAIC Big Data and AI (H) Working Group (minutes pending adoption): NAIC Big Data and Artificial Intelligence (H) Working Group, meeting minutes, remarks: "whether permissions are tested, whether actions are logged for company reconstruction" https://content.naic.org/sites/default/files/call_materials/minutes-bdaiwg081326-final.pdf
