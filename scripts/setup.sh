#!/usr/bin/env bash
# One-time local setup. Run from the repo root.
set -euo pipefail
python3.12 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]"
chmod +x scripts/*.sh
echo "setup OK. Activate with: source .venv/bin/activate"
