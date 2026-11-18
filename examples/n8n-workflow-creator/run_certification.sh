#!/usr/bin/env bash
# Verifier certification by mutation testing. Default: 12 template-titled scenarios on the REFERENCE executor (no keys, no Docker).
# Environment switches:  COUNT=24   LLM=1 (Data Designer writes titles; needs NVIDIA_API_KEY etc. in .env)
#                        EXECUTOR=both (real n8n too; needs the Docker stack and N8N_LAB_API_KEY, see docs/02-setup-and-reproduce.md)
# Usage: examples/n8n-workflow-creator/run_certification.sh [output-dir]   (must not already exist)
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -d .venv/bin ] && export PATH="$PWD/.venv/bin:$PATH"
command -v n8n-lab >/dev/null || { echo "n8n-lab not found: install with 'pip install -e .' (see docs/02-setup-and-reproduce.md)"; exit 1; }
OUT="${1:-artifacts/certification-$(date +%Y%m%d-%H%M%S)}"
COUNT="${COUNT:-12}"; EXECUTOR="${EXECUTOR:-reference}"
mkdir -p "$OUT"
TITLES="--no-llm"; if [ "${LLM:-0}" = 1 ]; then TITLES=""; fi
n8n-lab scenarios-dd --count "$COUNT" $TITLES --out "$OUT/scenarios.jsonl" 2>&1 | grep -v INFO | tail -9
ACT=""; [ "$EXECUTOR" = reference ] || ACT="--allow-activation"
n8n-lab certify --scenarios "$OUT/scenarios.jsonl" --executor "$EXECUTOR" $ACT --out "$OUT/run" > "$OUT/certify.log"
python3 - "$OUT/run/summary.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
for name, v in s["suites"].items():
    print(f"{name:22} controls {v['control_pass']}/{v['control_total']}  killed {v['killed']}/{v['applicable_mutants']}  "
          f"no_retry {v['per_mutant']['no_retry']['killed']}/{v['per_mutant']['no_retry']['applicable']}  errors {v['errors']}")
a = s["accepted"]; d = s["divergences"]
print(f"accepted (novel kill vs legacy): {a['count']}/{a['of']}   minimal cover: {s['minimal_cover']['size']} scenarios")
print(f"blind spots  generated: {s['blind_spots'] or 'none'}   legacy: {s['legacy_blind_spots'] or 'none'}")
print(f"reference vs n8n divergences: {d['count']} of {d['compared']}" if d["compared"] else "reference vs n8n: only one runtime executed")
print("report:", sys.argv[1].replace("summary.json", "report.html"))
PY
