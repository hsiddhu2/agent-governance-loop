REGION = us-east-1
export AWS_DEFAULT_REGION = $(REGION)

# Every resource carries an expires tag. Default is 60 days from today.
EXPIRES ?= $(shell python3 -c "import datetime as d; print(d.date.today() + d.timedelta(days=60))")
export EXPIRES
CDK_CTX = -c expires=$(EXPIRES)

.PHONY: check test lock package synth deploy-base discover deploy-policy enforce log-only deploy-agents deploy seed attack trace evidence reset destroy

# Every deploy names its stacks and passes --exclusively, so a deploy changes only
# what it names. The Gateway's policy mode changes only through `enforce` and
# `log-only`. Any other Gateway deploy keeps the mode the live Gateway runs in
# (LOG_ONLY before the first deploy, because no policies exist yet).
CURRENT_MODE = $(shell python scripts/policy_mode.py current || echo FAIL)
# Deploys synthesize with the AWS Solutions checks on, so nothing ships unchecked.
# The synth runs once. Its templates are checked against the live stacks for resource
# type changes, which CloudFormation would only find mid-update, and then that same
# cdk.out is deployed. Usage: $(call deploy,<stacks>,<extra context>)
define deploy
	rm -rf cdk.out
	cdk synth $(CDK_CTX) -c nag=true $(2) --quiet
	python scripts/check_type_changes.py $(1)
	cdk deploy --app cdk.out --exclusively --require-approval never $(1)
endef

# Run after every change. Lint, offline tests, a clean synth reviewed by the AWS
# Solutions and NIST 800-53 Rev 5 rule packs (unacknowledged findings and template
# validation issues fail it), a check that every acknowledged finding is disclosed in
# the README, and a check that the stacks do not depend on whether policies have been
# rendered. The synth starts from an empty cdk.out so a removed stack leaves nothing behind.
check: package
	ruff check .
	python -m pytest tests collector/tests -q
	rm -rf cdk.out
	cdk synth $(CDK_CTX) -c nag=true --quiet
	python scripts/check_deviations.py
	python scripts/check_outputs.py
	python scripts/check_stable_synth.py $(CDK_CTX) -c nag=true

# Offline checks for the scripts that read spans and gate enforcement. No AWS calls.
test:
	python -m pytest tests collector/tests -q

# Resolve the agent's dependencies for the runtime platform and pin them with hashes.
# Run on purpose after changing requirements.txt, then review the diff.
lock:
	uv pip compile agents/ops_agent/requirements.txt -o agents/ops_agent/requirements.lock \
	  --python-platform aarch64-manylinux2014 --python-version 3.12 \
	  --only-binary=:all: --generate-hashes --no-header -q

package:
	scripts/package_agent.sh

synth: package
	cdk synth $(CDK_CTX) --quiet

deploy-base: package
	@test "$(CURRENT_MODE)" != FAIL || (echo "could not read the Gateway's policy mode" && exit 1)
	$(call deploy,AglKeys AglAudit AglNetwork AglDataStaging AglDataProduction AglTools AglGateway,-c policy_mode=$(CURRENT_MODE))

# Tool names come from the live Gateway, so policies are rendered after it exists.
discover:
	python scripts/discover_tools.py
	python scripts/render_policy.py

deploy-policy: package
	$(call deploy,AglPolicy)

# Enforcement is switched on only after a LOG_ONLY check shows the policies
# allow at least one tool. With default deny, an empty allow set hides every tool.
enforce: package
	python scripts/policy_mode.py check
	$(call deploy,AglGateway,-c policy_mode=ENFORCE)

# Record decisions without applying them. Shows what policy would have stopped.
log-only: package
	$(call deploy,AglGateway,-c policy_mode=LOG_ONLY)

deploy-agents: package
	$(call deploy,AglAgents)

deploy: deploy-base discover deploy-policy enforce deploy-agents

seed:
	python scripts/seed.py

MODE ?= agent
attack:
	python scripts/attack.py --scenario $(SCENARIO) --mode $(MODE)

trace:
	python scripts/policy_trace.py 30

# An evidence pack for the Gateway from the live account, read-only, into a new
# folder under evidence/ (not committed). Add REDACT=--redact to share it.
SINCE ?= 24h
evidence:
	agentcore-evidence collect --gateway agl-gateway --region $(REGION) --since $(SINCE) \
	  --out evidence/$(shell date -u +%Y%m%dT%H%M%SZ) $(REDACT)

reset:
	python scripts/reset.py

# Removes everything. The claims stores are protected like stores of record, so
# their deletion protection and backups are undone on purpose first. The runtime's
# log group is created by AgentCore, not the stacks, so it is removed last.
destroy: package
	python scripts/prepare_destroy.py
	cdk destroy --all --force $(CDK_CTX)
	python scripts/remove_service_logs.py
