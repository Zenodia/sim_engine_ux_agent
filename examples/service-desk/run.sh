#!/usr/bin/env bash
# Kick-start: 100 synthetic users, old vs new service-desk agent, rules only. No keys, no Docker, no inference.
# Usage: examples/service-desk/run.sh [output-dir]   (default: a fresh artifacts/service-desk-<timestamp> folder)
set -euo pipefail
cd "$(dirname "$0")/../.."
[ -d .venv/bin ] && export PATH="$PWD/.venv/bin:$PATH"
command -v sim-engine >/dev/null || { echo "sim-engine not found: install with 'pip install -e .' (see docs/02-setup-and-reproduce.md)"; exit 1; }
OUT="${1:-artifacts/service-desk-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"
sim-engine generate --count 100 --suite stress --out "$OUT/stress.jsonl"
sim-engine compare --scenarios "$OUT/stress.jsonl" --out "$OUT/comparison" | tail -1
set +e; sim-engine gate --run "$OUT/comparison" > "$OUT/gate.txt"; GATE=$?; set -e   # exit 2 = hold, not a crash
sim-engine report --run "$OUT/comparison" | tail -1
python3 - "$OUT" "$GATE" <<'PY'
import json, sys
out, gate = sys.argv[1], sys.argv[2]
s = json.load(open(f"{out}/comparison/summary.json")); g = json.load(open(f"{out}/comparison/gate.json"))
for arm in ("baseline", "candidate"):
    print(f"{arm:9} success {round(s[arm]['success_rate'] * s[arm]['n'])}/{s[arm]['n']}  "
          f"safety_failures={s[arm]['safety_failures']}  execution_errors={s[arm]['execution_errors']}")
print(f"gate decision: {g['decision']} (exit code {gate}); production authorized: {g['production_promotion_authorized']}")
print(f"open {out}/comparison/report.html")
PY
