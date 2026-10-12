REGION = us-east-1
export AWS_DEFAULT_REGION = $(REGION)

# Every resource carries an expires tag. Default is 60 days from today.
EXPIRES ?= $(shell python3 -c "import datetime as d; print(d.date.today() + d.timedelta(days=60))")
export EXPIRES
CDK_CTX = -c expires=$(EXPIRES)

.PHONY: package synth deploy-base discover deploy-policy deploy seed attack trace reset destroy

package:
	scripts/package_agent.sh

synth: package
	cdk synth $(CDK_CTX) --quiet

deploy-base: package
	cdk deploy AglData AglTools AglGateway $(CDK_CTX) --require-approval never

discover:
	python scripts/discover_tools.py
	python scripts/render_policy.py

deploy-policy: package
	cdk deploy AglPolicy AglAgents $(CDK_CTX) --require-approval never

deploy: deploy-base discover deploy-policy

seed:
	python scripts/seed.py

attack:
	python scripts/attack.py --scenario $(SCENARIO)

trace:
	python scripts/trace.py 30

reset:
	python scripts/reset.py

destroy:
	cdk destroy --all --force $(CDK_CTX)
