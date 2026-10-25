"""Render every policy template into the file the policy stack deploys.

Templates live in policies/cedar (permits and forbids) and policies/guardrails (output
screens). Each *.cedar.tmpl is rendered next to itself as a .cedar file, with the tool
names and Gateway ARN that `make discover` read from the live Gateway and the agents'
principals. A rendered file whose template is gone is removed, so it cannot keep
enforcing.
"""
import argparse
import json
import re
import sys
from pathlib import Path

TOOL = re.compile(r"\{\{TOOL:(\w+)\}\}")
GATEWAY = "{{GATEWAY_ARN}}"
PRINCIPAL = re.compile(r"\{\{PRINCIPAL:(\w+)\}\}")
ANY_PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")
# Permits and forbids, then output screens. The policy stack reads the same two folders.
POLICY_DIRS = ("cedar", "guardrails")


def render(template: str, tool_names: dict[str, str], gateway_arn: str,
           principals: dict[str, str] | None = None) -> str:
    """Fill a template. Raises if a tool or principal is unknown or any placeholder is left."""
    principals = principals or {}

    def tool(m: re.Match) -> str:
        if m.group(1) not in tool_names:
            raise KeyError(f"no discovered tool named {m.group(1)!r}")
        return tool_names[m.group(1)]

    def principal(m: re.Match) -> str:
        if m.group(1) not in principals:
            raise KeyError(f"no deployed principal named {m.group(1)!r}")
        return principals[m.group(1)]

    text = TOOL.sub(tool, template).replace(GATEWAY, gateway_arn)
    text = PRINCIPAL.sub(principal, text)
    left = ANY_PLACEHOLDER.findall(text)
    if left:
        raise ValueError(f"unfilled placeholders: {left}")
    return text


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--names", default="policies/tool_names.json")
    p.add_argument("--gateway", default="policies/gateway.json")
    p.add_argument("--root", default="policies", help="the folder that holds the policy folders")
    a = p.parse_args()

    names = json.loads(Path(a.names).read_text())
    gateway = json.loads(Path(a.gateway).read_text())
    gateway_arn, principals = gateway["arn"], gateway.get("principals", {})
    dirs = [Path(a.root, d) for d in POLICY_DIRS]
    # Render everything before writing anything, so one bad template changes no file.
    outputs = {}
    for tmpl in sorted(t for d in dirs for t in d.glob("*.cedar.tmpl")):
        try:
            target = tmpl.with_name(tmpl.name.removesuffix(".tmpl"))
            outputs[target] = render(tmpl.read_text(), names, gateway_arn, principals)
        except (KeyError, ValueError) as e:
            sys.exit(f"{tmpl}: {e}")
    # Every rendered file becomes a live policy, so one left over from a removed or
    # renamed template would keep enforcing. Remove those first.
    for path in (p for d in dirs for p in stale_outputs(d, set(outputs))):
        path.unlink()
        print(f"removed {path}: no template renders it")
    for target, rendered in outputs.items():
        target.write_text(rendered)
        print(f"--- {target}\n{rendered}")


def stale_outputs(out_dir: Path, current: set[Path]) -> list[Path]:
    """Rendered policy files in `out_dir` that no current template produces."""
    return sorted(p for p in out_dir.glob("*.cedar") if p not in current)


if __name__ == "__main__":
    main()
