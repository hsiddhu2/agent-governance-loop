"""Render every *.cedar.tmpl into a .cedar file using discovered tool names and Gateway ARN."""
import argparse
import json
import re
import sys
from pathlib import Path

TOOL = re.compile(r"\{\{TOOL:(\w+)\}\}")
GATEWAY = "{{GATEWAY_ARN}}"
ANY_PLACEHOLDER = re.compile(r"\{\{[^}]*\}\}")


def render(template: str, tool_names: dict[str, str], gateway_arn: str) -> str:
    """Fill a template. Raises if a tool is unknown or any placeholder is left."""
    def tool(m: re.Match) -> str:
        if m.group(1) not in tool_names:
            raise KeyError(f"no discovered tool named {m.group(1)!r}")
        return tool_names[m.group(1)]

    text = TOOL.sub(tool, template).replace(GATEWAY, gateway_arn)
    left = ANY_PLACEHOLDER.findall(text)
    if left:
        raise ValueError(f"unfilled placeholders: {left}")
    return text


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--names", default="policies/cedar/tool_names.json")
    p.add_argument("--gateway", default="policies/cedar/gateway.json")
    p.add_argument("--templates", default="policies/cedar")
    p.add_argument("--out", default="policies/cedar")
    a = p.parse_args()

    names = json.loads(Path(a.names).read_text())
    gateway_arn = json.loads(Path(a.gateway).read_text())["arn"]
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tmpl in sorted(Path(a.templates).glob("*.cedar.tmpl")):
        try:
            rendered = render(tmpl.read_text(), names, gateway_arn)
        except (KeyError, ValueError) as e:
            sys.exit(f"{tmpl}: {e}")
        target = out_dir / tmpl.name.removesuffix(".tmpl")
        target.write_text(rendered)
        print(f"--- {target}\n{rendered}")


if __name__ == "__main__":
    main()
