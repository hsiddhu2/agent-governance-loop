# Tests

Offline tests. None of them calls AWS. `make test` runs these and the evidence collector's own tests in [collector/tests/](../collector/tests/). `make check` runs them too, with lint and the synth checks.

Each folder holds the tests for one part of the pattern.

| Folder | Protects | Code under test |
|---|---|---|
| [`policies/`](policies/) | The rules the policy engine gets | `policies/*/*.cedar.tmpl`, `scripts/render_policy.py`, `scripts/discover_tools.py`, `infra/stacks/policy_stack.py` |
| [`infra/`](infra/) | What the stacks build | `infra/stacks/` |
| [`tools/`](tools/) | What the tools return, and the synthetic data they read | `tools/ops/handler.py`, `tools/support/handler.py`, `scripts/synthetic.py` |
| [`checks/`](checks/) | The checks that stop a bad build, deploy or test run | `scripts/check_*.py`, the purge guard in `scripts/attack.py` |
| [`evidence/`](evidence/) | The scripts that read decisions back and decide whether enforcement is safe | `scripts/policy_mode.py`, `scripts/policy_trace.py`, `scripts/spans.py`, `scripts/screen_matrix.py` |

## What each file checks

| File | Checks that |
|---|---|
| `policies/test_cedar_templates.py` | Every template names the Gateway as its resource, a permit names exactly one principal, and every placeholder can be filled. An unknown tool or principal stops the render |
| `policies/test_policy_statement.py` | The policy stack drops each file's comment header, refuses a file with no effect, and creates the policies one after another: permits, then forbids, then screens |
| `policies/test_policy_validation_mode.py` | Only a forbid or a screen may skip the analyzer's semantic checks, and only by saying why |
| `policies/test_render_stale.py` | A rendered policy whose template is gone is found as stale, and the next render removes it |
| `policies/test_discover_hint.py` | Discovery explains what to do when the Gateway does not list a tool |
| `infra/test_audit_trail.py` | The Gateway trail records Gateway calls only, signs its files, and accepts files from itself only |
| `infra/test_gateway_role_trust.py` | The Gateway's role has one trust statement, limited to this account and to Gateways whose name starts with agl-gateway |
| `infra/test_tool_role_order.py` | A tool function is not updated before its role's permissions are in place |
| `infra/test_registry.py` | Each catalog record says what the templates and schemas say, and the reviewer approves only a match |
| `tools/test_ops_tools.py` | A claim or store that does not exist comes back as a message the caller can read, in the shape a screen can check |
| `tools/test_support_tools.py` | `get_ticket` returns only its declared fields, and an unknown ticket in the same shape |
| `tools/test_synthetic_tickets.py` | The synthetic tickets carry what the support scenarios need |
| `checks/test_attack_guard.py` | A scenario that targets the purge runs under LOG_ONLY only when confirmed, through the agent or directly |
| `checks/test_check_outputs.py` | No stack output carries a secret |
| `checks/test_deviations.py` | The README's design review table and the rules accepted in code match |
| `checks/test_type_changes.py` | A deploy stops when a resource would change type under the same logical id |
| `evidence/test_span_checks.py` | Decision spans are read whole, a trace passes only on a deny that names its policy, the live mode is read correctly, and enforcement is switched on only when every policy is ACTIVE and a tool is allowed |
| `evidence/test_screen_matrix.py` | The screen matrix reads each call and sorts each field correctly |

`conftest.py` puts `scripts/` and `infra/` on the import path, so the tests import scripts and stacks the way `make` runs them.
