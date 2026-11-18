#!/usr/bin/env bash
# Kick-start for the n8n example: 100 creator users through offline, shadow, canary, expansion, full and a rollback drill
# on the Python REFERENCE executor. No keys, no Docker, no inference (about 1 minute). Never proof that n8n ran anything.
# Usage: examples/n8n-workflow-creator/run_reference.sh [output-dir]   (must not already exist)
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -d .venv/bin ] && export PATH="$PWD/.venv/bin:$PATH"
command -v n8n-lab >/dev/null || { echo "n8n-lab not found: install with 'pip install -e .' (see docs/02-setup-and-reproduce.md)"; exit 1; }
OUT="${1:-artifacts/n8n-reference-$(date +%Y%m%d-%H%M%S)}"
n8n-lab demo --count 100 --out "$OUT" | tail -1
python3 - "$OUT" <<'PY'
import json, sys
out = sys.argv[1]
for stage in ("offline", "shadow", "canary", "expansion", "full"):
    e = json.load(open(f"{out}/{stage}/evidence.json"))
    ok = e["candidate_observations"] - e["candidate_failures"]
    print(f"{stage:9} candidate {ok}/{e['candidate_observations']}  baseline failures {e['baseline_failures']}/{e['baseline_observations']}  passed={e['passed']}")
print("rollback drill phase:", json.load(open(f"{out}/rollback.json"))["phase"])
PY
