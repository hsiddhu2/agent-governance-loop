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
# A policy starts out recording its decisions without applying them only by saying why:
#   // enforcement: LOG_ONLY because <reason>
# Every other policy is ACTIVE. Removing the line, in a reviewed change, applies it.
ENFORCEMENT_LINE = re.compile(r"^\s*//\s*enforcement:(.*)$", re.M)
LOG_ONLY = re.compile(r"^\s*LOG_ONLY\s+because\s+\S.*$")
# Effects that can only take access or output away. Neither grants anything.
NARROWING = ("forbid", "suppressOutput")
# Guardrail conditions and the suppressOutput effect are not Cedar.
# The service accepts them only as a `policy` definition, not a `cedar` one.
GUARDRAIL = re.compile(r"\bBedrockGuardrails::|^\s*suppressOutput\s*\(|\btemporal\s*\{", re.M)
EFFECTS = ("permit", "forbid", "suppressOutput")


def load_policy_statement(path: Path) -> str:
    """The statement in a policy file, without its comment header.

    The files keep their comments for the people who read them. The service rejects a
    `policy` definition whose effect is preceded by `//` lines, and reports it as an
    invalid effect, so what is sent starts at the effect. Line breaks inside the
    statement are kept as written.
    """
    lines = [line for line in path.read_text().splitlines() if not line.lstrip().startswith("//")]
    while lines and not lines[0].strip():
        lines.pop(0)
    statement = "\n".join(lines)
    if not statement.startswith(EFFECTS):
        raise ValueError(f"{path.name}: the statement must start with one of {', '.join(EFFECTS)}")
    return statement


def creation_order(path: Path) -> tuple[int, str]:
    """Permits, then forbids, then output screens, each group by name."""
    effect = load_policy_statement(path).split("(", 1)[0].strip()
    return EFFECTS.index(effect), path.name


# Permits and forbids, then output screens. scripts/render_policy.py writes the same two.
POLICY_DIRS = ("cedar", "guardrails")


def rendered_policies(policies_dir: Path) -> list[Path]:
    """Every rendered policy file, from both policy folders, ordered by file name."""
    return sorted((p for d in POLICY_DIRS for p in Path(policies_dir, d).glob("*.cedar") if p.is_file()),
                  key=lambda p: p.name)


def validation_mode(cedar: str, name: str) -> ac.PolicyValidationMode:
    lines = VALIDATION_LINE.findall(cedar)
    if not lines:
        return ac.PolicyValidationMode.FAIL_ON_ANY_FINDINGS
    if len(lines) > 1 or not OPT_OUT.match(lines[0]):
        raise ValueError(f"{name}: write '// validation: IGNORE_ALL_FINDINGS because <reason>' once")
    # An unchecked permit is how an overly broad allow slips through. Only a policy that
    # narrows, a forbid or an output screen, may opt out.
    if not code_of(cedar).lstrip().startswith(NARROWING):
        raise ValueError(f"{name}: only a forbid or suppressOutput policy may skip "
                         "the analyzer's semantic checks")
    return ac.PolicyValidationMode.IGNORE_ALL_FINDINGS


def code_of(cedar: str) -> str:
    return "\n".join(line for line in cedar.splitlines() if not line.strip().startswith("//"))


def uses_guardrails(cedar: str) -> bool:
    return bool(GUARDRAIL.search(code_of(cedar)))


def enforcement_mode(cedar: str, name: str) -> str:
    lines = ENFORCEMENT_LINE.findall(cedar)
    if not lines:
        return "ACTIVE"
    if len(lines) > 1 or not LOG_ONLY.match(lines[0]):
        raise ValueError(f"{name}: write '// enforcement: LOG_ONLY because <reason>' once")
    return "LOG_ONLY"


class PolicyStack(cdk.Stack):
    """One AgentCore Policy per rendered policy file, added to the Gateway's engine.

    Each file holds a single statement, and the file name becomes the policy
    name, so the determining policy in a trace maps straight back to a file.
    """

    def __init__(self, scope: Construct, id: str, engine: ac.IPolicyEngine,
                 policies_dir: Path, targets: list[Construct], **kw):
        super().__init__(scope, id, **kw)

        # No files yet means no policies yet: the engine then denies everything,
        # which is why the Gateway stays in LOG_ONLY until `make enforce`.
        #
        # One change at a time. In two deploys in this account, a valid permit was refused for
        # naming an action "that does not exist on the target gateway" while other policies
        # were being created in the same engine. The same policy was accepted on its own.
        # AWS has not confirmed the cause. Each
        # policy waits for the one before it: permits first, then forbids, then screens.
        previous = None
        for path in sorted(rendered_policies(policies_dir), key=creation_order):
            cedar = path.read_text()
            statement = load_policy_statement(path)
            mode = enforcement_mode(cedar, path.name)
            validation = validation_mode(cedar, path.name)
            if uses_guardrails(cedar):
                # The Policy construct writes a `cedar` definition. A guardrail statement
                # needs the `policy` member, so it is declared on the resource itself.
                # See docs/guardrail-policies.md.
                policy = ac.CfnPolicy(
                    self, path.stem,
                    name=path.stem,
                    policy_engine_id=engine.policy_engine_id,
                    definition=ac.CfnPolicy.PolicyDefinitionProperty(
                        policy=ac.CfnPolicy.PolicyStatementProperty(statement=statement)),
                    validation_mode=validation.value,
                    enforcement_mode=mode,
                )
                # The data path is checked against the tool's output schema, so the targets
                # must exist first. They are in the Gateway stack, so this becomes a
                # dependency on that stack, not on the target resources.
                for target in targets:
                    policy.node.add_dependency(target)
                if previous:
                    policy.node.add_dependency(previous)
                previous = policy
                cdk.CfnOutput(self, f"{path.stem}Id", value=policy.attr_policy_id)
                continue
            # Plain Cedar keeps its comments: Cedar accepts them, and the live policy then
            # says why it exists to anyone who reads it from the engine.
            policy = ac.Policy(
                self, path.stem,
                policy_engine=engine,
                policy_name=path.stem,
                statement=ac.PolicyStatement.from_cedar(cedar),
                validation_mode=validation,
            )
            # The construct has no enforcement-mode property. The resource does.
            if mode != "ACTIVE":
                policy.node.default_child.add_property_override("EnforcementMode", mode)
            if previous:
                policy.node.add_dependency(previous)
            previous = policy
            cdk.CfnOutput(self, f"{path.stem}Id", value=policy.policy_id)

        # Always name the engine, even with no policies yet, so the Gateway stack
        # publishes the same outputs before and after discovery.
        cdk.CfnOutput(self, "PolicyEngineId", value=engine.policy_engine_id)
