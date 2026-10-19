import re
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as ac
from constructs import Construct

# A policy opts out of the analyzer's semantic checks only by saying why, in one line:
#   // validation: IGNORE_ALL_FINDINGS because <reason>
# Schema checks still run on it. Every other policy is FAIL_ON_ANY_FINDINGS.
VALIDATION_LINE = re.compile(r"^\s*//\s*validation:(.*)$", re.M)
OPT_OUT = re.compile(r"^\s*IGNORE_ALL_FINDINGS\s+because\s+\S.*$")


def rendered_policies(cedar_dir: Path) -> list[Path]:
    return sorted(p for p in cedar_dir.glob("*.cedar") if p.is_file())


def validation_mode(cedar: str, name: str) -> ac.PolicyValidationMode:
    lines = VALIDATION_LINE.findall(cedar)
    if not lines:
        return ac.PolicyValidationMode.FAIL_ON_ANY_FINDINGS
    if len(lines) > 1 or not OPT_OUT.match(lines[0]):
        raise ValueError(f"{name}: write '// validation: IGNORE_ALL_FINDINGS because <reason>' once")
    # An unchecked permit is how an overly broad allow slips through. Only a deny may opt out.
    code = "\n".join(line for line in cedar.splitlines() if not line.strip().startswith("//"))
    if not code.lstrip().startswith("forbid"):
        raise ValueError(f"{name}: only a forbid policy may skip the analyzer's semantic checks")
    return ac.PolicyValidationMode.IGNORE_ALL_FINDINGS


class PolicyStack(cdk.Stack):
    """One AgentCore Policy per rendered Cedar file, added to the Gateway's engine.

    Each file holds a single statement, and the file name becomes the policy
    name, so the determining policy in a trace maps straight back to a file.
    """

    def __init__(self, scope: Construct, id: str, engine: ac.IPolicyEngine,
                 cedar_dir: Path, **kw):
        super().__init__(scope, id, **kw)

        # No files yet means no policies yet: the engine then denies everything,
        # which is why the Gateway stays in LOG_ONLY until `make enforce`.
        for path in rendered_policies(cedar_dir):
            cedar = path.read_text()
            policy = ac.Policy(
                self, path.stem,
                policy_engine=engine,
                policy_name=path.stem,
                statement=ac.PolicyStatement.from_cedar(cedar),
                validation_mode=validation_mode(cedar, path.name),
            )
            cdk.CfnOutput(self, f"{path.stem}Id", value=policy.policy_id)

        # Always name the engine, even with no policies yet, so the Gateway stack
        # publishes the same outputs before and after discovery.
        cdk.CfnOutput(self, "PolicyEngineId", value=engine.policy_engine_id)
