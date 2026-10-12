from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from constructs import Construct


def rendered_policies(cedar_dir: Path) -> list[Path]:
    return sorted(p for p in cedar_dir.glob("*.cedar") if p.is_file())


class PolicyStack(cdk.Stack):
    """One AgentCore Policy per rendered Cedar file, added to the Gateway's engine.

    Each file holds a single statement, and the file name becomes the policy
    name, so the determining policy in a trace maps straight back to a file.
    """

    def __init__(self, scope: Construct, id: str, engine: ac.IPolicyEngine,
                 cedar_dir: Path, **kw):
        super().__init__(scope, id, **kw)

        files = rendered_policies(cedar_dir)
        if not files:
            raise RuntimeError(f"No rendered .cedar files in {cedar_dir}. Run `make discover`.")

        for path in files:
            policy = ac.Policy(
                self, path.stem,
                policy_engine=engine,
                policy_name=path.stem,
                statement=ac.PolicyStatement.from_cedar(path.read_text()),
                validation_mode=ac.PolicyValidationMode.FAIL_ON_ANY_FINDINGS,
            )
            cdk.CfnOutput(self, f"{path.stem}Id", value=policy.policy_id)
