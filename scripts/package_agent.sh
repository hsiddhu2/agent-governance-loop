#!/usr/bin/env bash
# Build the Ops Agent bundle for AgentCore Runtime direct code deploy:
# agent source plus dependencies resolved for Linux arm64, Python 3.12.
set -euo pipefail
OUT=build/ops_agent
rm -rf "$OUT"
mkdir -p "$OUT"
python -m pip install -q \
  --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 \
  --only-binary=:all: --target "$OUT" \
  -r agents/ops_agent/requirements.txt
cp agents/ops_agent/main.py "$OUT/"
echo "packaged $OUT ($(du -sh "$OUT" | cut -f1))"
