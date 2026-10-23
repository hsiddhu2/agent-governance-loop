"""What the policy stack sends for each file: the statement, without its comment header."""
from pathlib import Path

import pytest

from stacks.policy_stack import load_policy_statement

ROOT = Path(__file__).resolve().parent.parent
SCREEN = """suppressOutput(
  principal,
  action == AgentCore::Action::"ops___get_claim_record",
  resource == AgentCore::Gateway::"g"
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(
    ["US_SOCIAL_SECURITY_NUMBER"],
    [context.output.policyholder]
  ).count() > 0
};"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "p.cedar"
    path.write_text(text)
    return path


def test_comment_header_is_dropped_and_line_breaks_kept(tmp_path):
    header = "".join(f"// comment {n}\n" for n in range(9))
    statement = load_policy_statement(write(tmp_path, header + "\n" + SCREEN + "\n"))
    assert statement.startswith("suppressOutput(")
    assert statement == SCREEN


def test_indented_comment_lines_are_dropped(tmp_path):
    text = SCREEN.replace("when guardrails {", "  // why this threshold\nwhen guardrails {")
    assert "why this threshold" not in load_policy_statement(write(tmp_path, text))


def test_a_file_with_no_effect_is_refused(tmp_path):
    with pytest.raises(ValueError, match="must start with"):
        load_policy_statement(write(tmp_path, "// only a comment\nprincipal, action, resource;\n"))


@pytest.mark.parametrize("path", sorted(ROOT.glob("policies/cedar/*.cedar.tmpl")), ids=lambda p: p.name)
def test_every_template_starts_at_its_effect(path):
    assert load_policy_statement(path).startswith(("permit", "forbid", "suppressOutput"))


def test_policies_are_created_one_after_another(tmp_path):
    import aws_cdk as cdk
    from aws_cdk import aws_bedrockagentcore as ac
    from aws_cdk.assertions import Template
    from constructs import Construct

    from stacks.policy_stack import PolicyStack

    gw = 'resource == AgentCore::Gateway::"g"'
    (tmp_path / "b_screen.cedar").write_text(
        "// validation: IGNORE_ALL_FINDINGS because opaque\n"
        f'suppressOutput(principal, action == AgentCore::Action::"t", {gw}) when guardrails {{ x }};')
    (tmp_path / "c_forbid.cedar").write_text(f"forbid(principal, action, {gw});")
    (tmp_path / "z_permit.cedar").write_text(f"permit(principal, action, {gw});")
    app = cdk.App()
    env = cdk.Environment(region="us-east-1")
    holder = cdk.Stack(app, "Holder", env=env)
    engine = ac.PolicyEngine(holder, "Engine", policy_engine_name="e")
    stack = PolicyStack(app, "P", engine=engine, cedar_dir=tmp_path,
                        targets=[Construct(holder, "T")], env=env)
    resources = Template.from_stack(stack).to_json()["Resources"]
    by_name = {r["Properties"]["Name"]: (k, r) for k, r in resources.items()
               if r["Type"].endswith("::Policy")}
    permit_id, _ = by_name["z_permit"]
    forbid_id, forbid = by_name["c_forbid"]
    _, screen = by_name["b_screen"]
    assert permit_id in forbid.get("DependsOn", [])
    assert forbid_id in screen.get("DependsOn", [])
