"""Which policies may skip the analyzer's semantic checks, and how they must say why."""
import pytest
from aws_cdk import aws_bedrockagentcore as ac

from stacks.policy_stack import validation_mode

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
