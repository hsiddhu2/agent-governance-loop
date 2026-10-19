#!/usr/bin/env bash
# Build the Ops Agent bundle for AgentCore Runtime direct code deploy:
# agent source plus the locked dependencies for Linux arm64, Python 3.12.
# Installing from the lock with hashes means the same commit builds the same bundle.
set -euo pipefail
OUT=build/ops_agent
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
rm -rf "$OUT"
mkdir -p "$OUT"
uv pip install -q \
  --python-platform aarch64-manylinux2014 --python-version 3.12 \
  --only-binary=:all: --require-hashes --no-deps --target "$OUT" \
  -r agents/ops_agent/requirements.lock
cp agents/ops_agent/main.py "$OUT/"

# Installing into a target folder writes launcher scripts that point at the Python
# that ran the install, which does not exist in the runtime. Point them at the
# runtime's own python3 instead.
python3 - "$OUT/bin" <<'EOF'
import sys
from pathlib import Path

for script in Path(sys.argv[1]).iterdir():
    lines = script.read_text().splitlines(keepends=True)
    if lines[:1] == ["#!/bin/sh\n"] and lines[1:2] and lines[1].startswith("'''exec'"):
        body = lines[3:]
    elif lines[:1] and lines[0].startswith("#!") and "python" in lines[0]:
        body = lines[1:]
    else:
        continue
    script.write_text("#!/usr/bin/env python3\n" + "".join(body))
EOF

# Nothing in the bundle may refer to this machine.
if grep -rIl --fixed-strings "$PWD" "$OUT" >/dev/null; then
  echo "bundle still refers to the build machine:" >&2
  grep -rIl --fixed-strings "$PWD" "$OUT" >&2
  exit 1
fi
echo "packaged $OUT ($(du -sh "$OUT" | cut -f1))"
