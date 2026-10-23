"""Rules every Cedar template must follow before it reaches the policy engine.

AgentCore rejects a policy whose resource is left open, and the analyzer judges
policies by the principal, action and resource they name. These checks catch the
first kind of rejection offline and keep each template explicit about what it covers.
"""
import re
from pathlib import Path

import pytest

from render_policy import render

TEMPLATES = sorted(Path(__file__).resolve().parent.parent.glob("policies/cedar/*.cedar.tmpl"))
SCOPE = re.compile(r"\b(permit|forbid|suppressOutput)\s*\((.*?)\)\s*(when|unless|;)", re.S)
GATEWAY_RESOURCE = 'resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"'
FAKE_GATEWAY = "arn:aws:bedrock-agentcore:us-east-1:example:gateway/g"


def statement(path: Path) -> tuple[str, str]:
    code = "\n".join(line for line in path.read_text().splitlines() if not line.strip().startswith("//"))
    found = SCOPE.findall(code)
    assert len(found) == 1, f"{path.name}: expected exactly one statement, found {len(found)}"
    return found[0][0], found[0][1]


def test_templates_exist():
    assert TEMPLATES


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_resource_is_pinned_to_the_gateway(path):
    _, scope = statement(path)
    assert GATEWAY_RESOURCE in scope, f"{path.name}: resource must be {GATEWAY_RESOURCE}"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_permit_names_a_principal_type(path):
    effect, scope = statement(path)
    if effect == "permit":
        assert re.search(r"principal\s+(is|==)\s+AgentCore::", scope), \
            f"{path.name}: a permit must name who it allows"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_renders_with_nothing_left(path):
    names = {t: f"ops___{t}" for t in re.findall(r"\{\{TOOL:(\w+)\}\}", path.read_text())}
    principals = {p: f"client-{p}" for p in re.findall(r"\{\{PRINCIPAL:(\w+)\}\}", path.read_text())}
    out = render(path.read_text(), names, FAKE_GATEWAY, principals)
    assert "{{" not in out


def test_render_rejects_unknown_tool():
    with pytest.raises(KeyError):
        render('action == AgentCore::Action::"{{TOOL:missing}}"', {}, FAKE_GATEWAY)


def test_render_rejects_unknown_principal():
    with pytest.raises(KeyError):
        render('principal == AgentCore::OAuthUser::"{{PRINCIPAL:missing}}"', {}, FAKE_GATEWAY)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_permit_is_pinned_to_one_principal(path):
    effect, scope = statement(path)
    if effect == "permit":
        assert re.search(r'principal\s*==\s*AgentCore::OAuthUser::"\{\{PRINCIPAL:\w+\}\}"', scope), \
            f"{path.name}: a permit must name the one agent it allows"


def test_render_rejects_leftover_placeholder():
    with pytest.raises(ValueError):
        render("{{SOMETHING_ELSE}}", {}, FAKE_GATEWAY)
