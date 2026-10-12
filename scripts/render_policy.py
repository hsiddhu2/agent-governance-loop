"""Render every *.cedar.tmpl into a .cedar file using discovered tool names."""
import argparse
import json
import re
from pathlib import Path

TOKEN = re.compile(r"\{\{TOOL:(\w+)\}\}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--names", default="policies/cedar/tool_names.json")
    p.add_argument("--templates", default="policies/cedar")
    p.add_argument("--out", default="policies/cedar")
    a = p.parse_args()

    names = json.loads(Path(a.names).read_text())
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tmpl in sorted(Path(a.templates).glob("*.cedar.tmpl")):
        rendered = TOKEN.sub(lambda m: names[m.group(1)], tmpl.read_text())
        target = out_dir / tmpl.name.removesuffix(".tmpl")
        target.write_text(rendered)
        print(f"--- {target}\n{rendered}")


if __name__ == "__main__":
    main()
