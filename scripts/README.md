# Scripts

Every script runs from the repo root, which is how `make` runs them. Each one says what it does in its own docstring. This page groups them by role.

"Changes AWS" means the script creates, changes or deletes something in the account. Everything else only reads, or makes no AWS call at all.

## Setup and build

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `setup.sh` | you, once | Creates `.venv` with Python 3.12 and installs the repo and the evidence collector | No |
| `package_agent.sh` | `make package`, and before every synth and deploy | Builds each agent's code bundle with locked Linux arm64 dependencies into `build/` | No |

## Deploy steps

`make deploy` runs these in order, with the stack deploys between them.

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `discover_tools.py` | `make discover` | Reads the live Gateway's tool names, its ARN and each agent's client id, and writes `policies/tool_names.json` and `policies/gateway.json`. The other scripts import its helpers | No |
| `render_policy.py` | `make discover` | Fills the policy templates in `policies/cedar/` and `policies/guardrails/` from those two files | No |
| `policy_mode.py` | `make enforce` (`check`), and `make deploy-base` and `make deploy-registry` (`current`) | `current` prints the Gateway's live mode, so a redeploy keeps it. `check` confirms that every rendered policy exists in the engine with status ACTIVE and that a fresh tools/list policy span allows at least one tool, before enforcement is switched on | No |
| `registry_role.py` | `make deploy-registry` | Creates the Agent Registry's service-linked role if it is missing | Yes |
| `approve_catalog.py` | `make approve-catalog` | Approves each draft catalog record that matches what is deployed, and rejects the rest with the reason | Yes |

## Checks

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `check_deviations.py` | `make check` | Fails if a rule accepted in code is missing from the README's design review table, or the table lists one no longer accepted | No |
| `check_outputs.py` | `make check` | Fails when any stack output reads a resource attribute that names a secret, other than its ARN | No |
| `check_stable_synth.py` | `make check` | Builds the templates again with no rendered policies. Only the policy stack may differ | No |
| `check_type_changes.py` | every deploy | Stops a deploy when a resource would change type under the same logical id, which CloudFormation cannot update | No |

## Test bench, against the live Gateway

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `attack.py` | `make attack SCENARIO=<name>` | Runs a scenario through the agent (`MODE=agent`, the default) or calls the tool directly with the agent's credential (`MODE=direct`). Scenarios: `claims-cleanup`, `ticket-injection`, `claim-file` | Under LOG_ONLY the purge could really run on staging, so a purge scenario asks for `CONFIRM=purge` first, in either mode |
| `access_matrix.py` | `make matrix` | Calls every tool with each agent's credential, without the model, and fails if any decision differs from the expected one. Runs only under ENFORCE | No |
| `registry_find.py` | `make find` | Finds the purge tool in the catalog and calls it as the support agent, to show that finding a tool grants nothing | No |
| `screen_matrix.py` | `python scripts/screen_matrix.py --doc docs/screen-coverage.md` | Reads each of the 20 probe records three times through `get_claim_record` with the ops agent's credential and no model, joins each call to its policy decision, and with `--doc` writes the table in [docs/screen-coverage.md](../docs/screen-coverage.md). Raw results go to `evidence/` | No |

## Evidence and tracing

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `policy_trace.py` | `make trace` | Lists up to 20 of the newest policy decisions from the last 30 minutes, and passes if a deny names the policy that made it | No |
| `spans.py` | imported | Queries and parses the Gateway's decision spans in `aws/spans` | No |

`make evidence` runs the collector in [collector/](../collector/README.md). `SINCE=24h` sets how far back it reads, and `REDACT=--redact` makes a pack you can share.

## Data

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `seed.py` | `make seed` | Writes the synthetic claims, probe records and tickets to every store. Overwrites rows by key | Yes |
| `reset.py` | `make reset` | Checks the four stores exist, then seeds them again, for example after a purge | Yes |
| `synthetic.py` | imported | Generates the synthetic records from a fixed seed. Its docstring says which values come from reserved ranges | No |

## Teardown

`make destroy` runs these around the stack deletes.

| Script | Run by | What it does | Changes AWS |
|---|---|---|---|
| `prepare_destroy.py` | `make destroy`, first | Stops the Gateway trail, empties its bucket, turns off deletion protection on the stores and empties the backup vaults | Yes, deletes data |
| `remove_service_logs.py` | `make destroy`, last | Deletes the log groups AWS services created for the pattern, which the stacks do not own | Yes, deletes logs |
