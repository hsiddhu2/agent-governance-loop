"""Which policies may skip the analyzer's semantic checks, and how they must say why."""
import pytest
from aws_cdk import aws_bedrockagentcore as ac

from stacks.policy_stack import enforcement_mode, uses_guardrails, validation_mode

FORBID = 'forbid(principal, action, resource == AgentCore::Gateway::"g");'
PERMIT = 'permit(principal, action, resource == AgentCore::Gateway::"g");'
OPT_OUT = "// validation: IGNORE_ALL_FINDINGS because the deny is intended\n"


def test_default_is_strict():
    assert validation_mode(FORBID, "p").value == ac.PolicyValidationMode.FAIL_ON_ANY_FINDINGS.value


def test_forbid_may_opt_out_with_a_reason():
    assert validation_mode(OPT_OUT + FORBID, "p").value == ac.PolicyValidationMode.IGNORE_ALL_FINDINGS.value


@pytest.mark.parametrize("text", [
    "// validation: IGNORE_ALL_FINDINGS\n" + FORBID,
    "// validation: IGNORE_ALL_FINDINGS because\n" + FORBID,
    "// validation: FAIL_ON_ANY_FINDINGS because strict\n" + FORBID,
    OPT_OUT + OPT_OUT + FORBID,
])
def test_opt_out_must_be_one_line_with_a_reason(text):
    with pytest.raises(ValueError):
        validation_mode(text, "p")


def test_permit_may_not_opt_out():
    with pytest.raises(ValueError, match="only a forbid"):
        validation_mode(OPT_OUT + PERMIT, "p")


SCREEN = 'suppressOutput(principal, action, resource == AgentCore::Gateway::"g") when guardrails { x };'


def test_output_screen_may_opt_out_with_a_reason():
    assert validation_mode(OPT_OUT + SCREEN, "p").value == ac.PolicyValidationMode.IGNORE_ALL_FINDINGS.value


def test_policies_are_active_unless_they_say_why():
    assert enforcement_mode(FORBID, "p") == "ACTIVE"
    assert enforcement_mode("// enforcement: LOG_ONLY because measured first\n" + SCREEN, "p") == "LOG_ONLY"


@pytest.mark.parametrize("line", ["// enforcement: LOG_ONLY\n", "// enforcement: ACTIVE because yes\n"])
def test_log_only_needs_a_reason(line):
    with pytest.raises(ValueError):
        enforcement_mode(line + SCREEN, "p")


def test_guardrail_statements_are_not_cedar():
    assert uses_guardrails(SCREEN)
    prompt_check = 'BedrockGuardrails::PromptAttack(["JAILBREAK"], [context.input.prompt]).count() > 0'
    assert uses_guardrails(f"forbid(principal, action, resource) when {{ {prompt_check} }};")
    assert not uses_guardrails(FORBID)
    assert not uses_guardrails("// suppressOutput is mentioned only in a comment\n" + PERMIT)
