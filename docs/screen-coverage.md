# What the output screens catch

The screens on `get_claim_record` withhold a claim file when it carries certain kinds of sensitive information. This page records what they caught, one kind of field at a time, and what no screen can catch.

## How it was measured

`scripts/screen_matrix.py` reads each of the 20 probe records in staging through `get_claim_record`, with the ops agent's own credential and no model, three times each. A probe holds a single field from a full claim file, so a screen that fires on it fired on that field. Each call carries its own trace id, which the Gateway keeps, so its policy decision is found exactly in `aws/spans`.

At the time of the run the Gateway was in ENFORCE. `ops_screen_government_ids` was ACTIVE, so it withheld responses. `ops_screen_contact_details`, `ops_screen_financial` and `ops_screen_health_ids` were in LOG_ONLY, so they withheld nothing and their decision records show what they would have caught.

## Results

| Field | Category needed | Screen that tests it | Detected | Result |
|---|---|---|---|---|
| `name` | NAME | ops_screen_contact_details | NAME | caught in LOG_ONLY 3/3 |
| `date_of_birth` | none | - | - | no category exists |
| `ssn` | US_SOCIAL_SECURITY_NUMBER | ops_screen_government_ids | not recorded | caught, withheld 3/3 |
| `address` | ADDRESS | ops_screen_contact_details | ADDRESS | caught in LOG_ONLY 3/3 |
| `phone` | PHONE | ops_screen_contact_details | PHONE | caught in LOG_ONLY 3/3 |
| `email` | EMAIL | ops_screen_contact_details | EMAIL | caught in LOG_ONLY 3/3 |
| `driver_license` | DRIVER_ID | ops_screen_government_ids | not recorded | caught, withheld 3/3 |
| `passport` | US_PASSPORT_NUMBER | ops_screen_government_ids | not recorded | caught, withheld 3/3 |
| `bank_account` | US_BANK_ACCOUNT_NUMBER | ops_screen_financial | US_BANK_ACCOUNT_NUMBER | caught in LOG_ONLY 3/3 |
| `bank_routing` | US_BANK_ROUTING_NUMBER | ops_screen_financial | US_BANK_ROUTING_NUMBER | caught in LOG_ONLY 3/3 |
| `card` | CREDIT_DEBIT_CARD_NUMBER | ops_screen_financial | CREDIT_DEBIT_CARD_NUMBER | caught in LOG_ONLY 3/3 |
| `medical_record_number` | none | - | - | no category exists |
| `health_plan_member_id` | none | - | - | no category exists |
| `attending_physician` | NAME | ops_screen_contact_details | NAME | caught in LOG_ONLY 3/3 |
| `diagnosis` | none | - | - | no category exists |
| `icd10` | none | - | - | no category exists |
| `medications` | none | - | - | no category exists |
| `admitted` | none | - | - | no category exists |
| `discharged` | none | - | - | no category exists |
| `clinical_note` | none | - | - | no category exists |

What the results show:

- Every field with a category was caught every time. Each of the eight fields caught in LOG_ONLY matched only the screen that tests its category. For the three withheld fields, other screens' matches are not recorded.
- Nine of the twenty fields have no guardrail category: date of birth and eight health details. No screen can catch them. The tool that returns them is the control: `get_claim` never puts them in a response.
- `ops_screen_health_ids` matched nothing. Its two categories are Canadian and UK health numbers, and a US claim file has neither.
- A withheld response leaves no output decision in `aws/spans`, and no span names the screen. The withhold is recorded in the caller's error, which names the screen (HTTP 403, JSON-RPC error -32002), and in the call's CloudTrail event. What the detector found in a withheld response is not in the spans, the caller's error or CloudTrail.
- Each probe holds one value from synthetic data. Real text, where an identifier sits inside a sentence or is written another way, can score differently. Measure on your own data before relying on a screen.

## Against the HIPAA Safe Harbor identifiers

The Safe Harbor method of de-identification lists 18 identifiers that are removed ([45 CFR 164.514(b)(2)(i)](https://www.law.cornell.edu/cfr/text/45/164.514)). The table sets each against the categories the policy language accepts ([Guardrails in policies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html)) and against the measurements above. A screen that withholds a response is not de-identification, and nothing here shows HIPAA compliance. The table shows which identifiers a screen could support evidence for.

| Identifier (164.514(b)(2)(i)) | Category | Measured here |
|---|---|---|
| (A) Names | NAME | caught: `name`, `attending_physician` |
| (B) Geographic subdivisions smaller than a State | ADDRESS | caught: a full street address. A city or ZIP code alone was not tested |
| (C) Elements of dates, and ages over 89 | none for dates. AGE for an age | `date_of_birth`, `admitted`, `discharged`: no category |
| (D) Telephone numbers | PHONE | caught: `phone` |
| (E) Fax numbers | none of its own | not tested |
| (F) Electronic mail addresses | EMAIL | caught: `email` |
| (G) Social security numbers | US_SOCIAL_SECURITY_NUMBER | caught and withheld: `ssn` |
| (H) Medical record numbers | none | `medical_record_number`: no category |
| (I) Health plan beneficiary numbers | none for US plans | `health_plan_member_id`: no category |
| (J) Account numbers | US_BANK_ACCOUNT_NUMBER, CREDIT_DEBIT_CARD_NUMBER, INTERNATIONAL_BANK_ACCOUNT_NUMBER | caught: `bank_account`, `card`. An insurance policy number has no category |
| (K) Certificate/license numbers | DRIVER_ID for a driver's license | caught and withheld: `driver_license` |
| (L) Vehicle identifiers, including license plates | VEHICLE_IDENTIFICATION_NUMBER, LICENSE_PLATE | not tested |
| (M) Device identifiers and serial numbers | MAC_ADDRESS covers one kind | not tested |
| (N) Web URLs | URL | not tested |
| (O) IP address numbers | IP_ADDRESS | not tested |
| (P) Biometric identifiers | none | a text screen cannot see them |
| (Q) Full face photographs | none | a text screen cannot see them |
| (R) Any other unique identifying number or code | none in general | `icd10` and the other health fields: no category |

Six of the 18 have no category at all (C for dates, H, I, P, Q, R), and two of those, P and Q, cannot appear in text. Fax numbers (E) have no category of their own. For a health or life claim these are the identifiers that matter most. A screen at the Gateway is a backstop for them at best. The control is the shape of the tool: return only what the caller needs, as `get_claim` does.
