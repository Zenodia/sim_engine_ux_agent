# 2. Environment bring-up and step-by-step reproduction

Goal: reproduce every result in [the overview](01-overview.md), from no-key runs to real self-hosted n8n and
live model runs. Each step lists what you should see. Commands marked **(verified 2026-11-18)** were executed
exactly as written on the verification VM; the rest are carried over from earlier documentation and were not
re-run in this pass.

## 0. What you need, and which steps need which keys

| Step | Python | Docker | Keys |
|---|---|---|---|
| A. Service desk, rules only | yes | no | none |
| B. n8n reference lifecycle | yes | no | none |
| C. Real self-hosted n8n | yes | yes | `N8N_LAB_API_KEY` (created in the n8n UI) |
| C+. Live Sonnet creator on n8n | yes | yes | `SIM_LLM_API_KEY` (NVIDIA inference gateway) |
| D. Mutation certification | yes | for n8n only | none with `--no-llm`; `NVIDIA_API_KEY` for LLM-written titles |
| E. Optional: live service desk, SDG, NOOA, canary | yes | no | `SIM_LLM_API_KEY`; NOOA alias |

Prerequisites: Linux or WSL 2 (native Windows is not the supported target for NOOA), Python 3.12 or 3.13,
git, Docker with Compose v2 for steps C and D-on-n8n. Node.js is optional: it enables one extra test that executes the
compiled JavaScript outside n8n.

## 1. Install (verified 2026-11-18)

```bash
git clone <this-repository> && cd sim_engine_ux_agent
uv venv --python 3.12 .venv                       # or: python3.12 -m venv .venv
uv pip install -p .venv/bin/python -e ".[dev,sdg]" # or: source .venv/bin/activate && pip install -e ".[dev,sdg]"
export PATH="$PWD/.venv/bin:$PATH"                 # puts sim-engine and n8n-lab on PATH
pytest -q                                          # expect: 29 passed, 2 skipped
```

`[sdg]` installs `data-designer`; `[nooa]` (optional) installs NOOA. If you use an existing virtualenv, make sure it has
`pip` and the project installed (a bare Jupyter environment does not).

## 2. Configure `.env`

```bash
cp -n .env.example .env       # never overwrite an existing .env that already holds keys
```

`.env` is git-ignored and loaded automatically from the working directory; exported shell variables win. Variables:

| Variable | Used by | Notes |
|---|---|---|
| `SIM_LLM_BASE_URL`, `SIM_LLM_MODEL`, `SIM_LLM_API_KEY` | Agent / creator under test | Defaults: `https://inference-api.nvidia.com/v1`, `aws/anthropic/bedrock-claude-sonnet-5`. Set the key explicitly (see warning below) |
| `SIM_CANDIDATE_LLM_MAX_TOKENS=2048` | Candidate output budget | Sonnet can spend tokens on reasoning; 512 truncated a real denial response |
| `SIM_SDG_LLM_*` | Nemotron 3 Super synthetic-user text | Thinking disabled by default so short JSON is not starved of tokens |
| `SIM_INPUT_USD_PER_MILLION`, `SIM_OUTPUT_USD_PER_MILLION` | Cost accounting | Leave empty and cost stays `null` (unknown), which blocks a configured cost gate |
| `N8N_LAB_URL`, `N8N_LAB_API_KEY`, `N8N_LAB_FIXTURE_URL`, `N8N_LAB_FIXTURE_INTERNAL_URL`, `N8N_LAB_PUBLISH_ACTION` | Real n8n | Defaults match the Compose stack; `publish` for n8n 2.x, `activate` for older instances |
| `N8N_LAB_GATEWAY_TOKEN` | Draft gateway | A random local token of at least 16 characters, only when serving the gateway |
| `NVIDIA_API_KEY`, `DATA_DESIGNER_MODEL`, `DD_END_POINT`, `DD_MAX_TOKENS` | Data Designer scenario titles | Endpoint `https://integrate.api.nvidia.com/v1`, model `nvidia/nemotron-3.5-lightning-30b-a3b` |

**Key hygiene.** Keys go only in `.env`, never in commands, issues, chat or commits. If a key was ever pasted
somewhere visible, treat it as exposed and rotate it. **Warning:** if `SIM_LLM_API_KEY` is unset the code falls back to
`NVIDIA_API_KEY`, which belongs to a different endpoint than the inference gateway; set both explicitly.

## A. Service desk, rules only, no keys (verified 2026-11-18)

Shortcut: `examples/service-desk/run.sh` runs the four commands below and prints the summary ([example README](../examples/service-desk/README.md)).

```bash
sim-engine generate --count 100 --suite stress --out artifacts/stress.jsonl
sim-engine compare  --scenarios artifacts/stress.jsonl --out artifacts/rules-comparison
sim-engine gate     --run artifacts/rules-comparison
sim-engine report   --run artifacts/rules-comparison     # open artifacts/rules-comparison/report.html
```

Expect baseline 20/100 successful flows, candidate 100/100 with zero errors, and
`decision: eligible_for_manual_review` (exit code 0). Exit code **2** means *hold*, not a crash. Use a **new** output folder
for each run; reusing one raises `FileExistsError` by design.

## B. n8n reference lifecycle, no keys (verified 2026-11-18, about 51 s)

Shortcut: `examples/n8n-workflow-creator/run_reference.sh` ([example README](../examples/n8n-workflow-creator/README.md)).

```bash
n8n-lab demo --count 100 --out artifacts/n8n-demo
```

Expect offline 100/100, shadow 100/100, canary and expansion all passing, full 100/100, then a rollback drill, and the message
"Reference migration demo completed. Actual n8n execution is a separate test." Reports are in `artifacts/n8n-demo/*/report.html`.
This is the Python reference only and is never proof that n8n ran anything.

## C. Real self-hosted n8n (verified 2026-11-18)

### C1. Start the stack

```bash
docker compose -f deploy/n8n/compose.yaml up -d --build
docker compose -f deploy/n8n/compose.yaml ps
curl -s http://127.0.0.1:5680/healthz        # expect {"status":"ok"}
```

The stack is a dedicated n8n 2.47.7 (set `N8N_LAB_IMAGE` to override) on loopback port **5680** and the fixture API on
**8091**, with named volumes. The Compose network must be `internal: false`: Docker does not forward published host ports for
services on an internal network, so the editor would be unreachable. This repository's `compose.yaml` already sets that; if you
have an older copy, run `sed -i 's/internal: true/internal: false/' deploy/n8n/compose.yaml`, then `docker compose ... down` and
`up -d --build` (volumes are kept).

### C2. Reach the editor from your laptop (remote VM only)

Ports are bound to the VM's loopback. Forward the editor port, for example with Brev
`brev port-forward <instance> -p 5680:5680`, or `ssh -L 5680:127.0.0.1:5680 -L 8091:127.0.0.1:8091 <user>@<host>`.
Only the editor needs forwarding for setup; the CLI runs on the VM and uses `127.0.0.1` directly.

### C3. Owner account and API key (manual, once)

1. Open http://localhost:5680 and create the owner account (a throwaway lab account is fine).
2. **Settings > n8n API > Create an API key.** Grant workflow create, read, update, delete and publish scopes. n8n shows the key once.
3. Put it in `.env`: `N8N_LAB_API_KEY=<key>` (and leave the other `N8N_LAB_*` defaults).

### C4. Run real executions

```bash
n8n-lab generate --count 4 --out artifacts/n8n-integration-tasks.jsonl
n8n-lab evaluate --tasks artifacts/n8n-integration-tasks.jsonl --executor n8n --allow-activation \
  --out artifacts/n8n-runtime-check
N8N_LAB_RUN_INTEGRATION=1 pytest tests/test_workflow_lab.py -m integration -q    # expect: 1 passed
```

Expect candidate 4/4 and baseline 0/4 (the baseline is deliberately defective); the integration test passes. Every webhook call
should return 200 (or the injected 500s for the baseline). `--allow-activation` lets the adapter import and *temporarily publish
only the new test workflows*, call their webhooks, and unpublish them in a `finally` block; it never updates or deletes
workflows it did not create. Created ids and cleanup state are in `n8n-created-workflows.json`.

Check that nothing is left published:

```bash
set -a; . ./.env; set +a
curl -s -H "X-N8N-API-KEY: $N8N_LAB_API_KEY" "http://127.0.0.1:5680/api/v1/workflows?active=true&limit=50"
```

### C5. Live Sonnet creator on real n8n (needs `SIM_LLM_API_KEY`, makes inference calls)

```bash
n8n-lab generate --count 6 --out artifacts/n8n-live-tasks.jsonl
n8n-lab evaluate --tasks artifacts/n8n-live-tasks.jsonl --creator llm --executor n8n --allow-activation \
  --out artifacts/n8n-live-creator
```

Expect candidate 6/6, baseline 0/6, about 8 s per flow, around 1 to 2 model calls per user, cost reported as unknown unless pricing is set.
Six candidates exceed the default promotion minimum of five observations; the live creator has its own release identity and
cannot be promoted on rules-only evidence.

### C6. Stop and clean up

```bash
docker compose -f deploy/n8n/compose.yaml down          # keeps volumes
docker compose -f deploy/n8n/compose.yaml down -v        # also deletes n8n and fixture data
```

Each real run leaves **unpublished** `sim-engine:*` drafts in the lab n8n; delete them in the editor if you want a clean list.

## D. Verifier certification by mutation testing (verified 2026-11-18)

Shortcut: `examples/n8n-workflow-creator/run_certification.sh` (env `COUNT`, `LLM=1`, `EXECUTOR=both`).

```bash
# 1. Generate scenarios with NeMo Data Designer
n8n-lab scenarios-dd --count 24 --out artifacts/mutation-cert/scenarios-24.jsonl         # LLM titles (needs NVIDIA_API_KEY etc.)
n8n-lab scenarios-dd --count 24 --no-llm --out artifacts/mutation-cert/scenarios-24.jsonl # template titles, no key, no inference

# 2. Mutation-test the verifier
n8n-lab certify --scenarios artifacts/mutation-cert/scenarios-24.jsonl --executor reference --out artifacts/mutation-cert/run-ref
n8n-lab certify --scenarios artifacts/mutation-cert/scenarios-24.jsonl --executor both --allow-activation --out artifacts/mutation-cert/run-24
```

Choose a new `--out` folder each time. With LLM titles, generation takes a few minutes because the endpoint rate-limits;
Data Designer retries 429 responses on its own. The `--executor both` run imports and publishes a few hundred
temporary workflows and took only a few minutes on the VM (about 1 s per cell on n8n in the 8-scenario smoke run).

Expect (24 scenarios, 9 mutants): all 24 controls pass on both runtimes; legacy suite kills 189/198, generated suite 90/165; legacy
`no_retry` 4/13 versus generated 7/13; 3 of 24 scenarios accepted; **0 divergences between the reference and n8n over 411 cells**.
Scenario sampling is not seeded, so the *exact* scenarios (and therefore some counts) differ between generations; the saved
`scenarios-*.jsonl` is the reproducible record, and re-running `certify` on the same file reproduces the matrix.
Outputs in the run folder: `summary.json`, `cells.json` (every cell), `report.html`, `n8n-created-workflows.json`.

## E. Optional paths carried over from earlier documentation (not re-run in this pass)

**Live service-desk model run and SDG** (needs `SIM_LLM_API_KEY`; calls cost money):

```bash
python scripts/inference_example.py                       # manual single request
python scripts/generate_sdg.py --count 100 --batch-size 5 --max-requests 20 --out artifacts/users-100-sdg.jsonl   # add --resume after a failure
sim-engine generate --count 8 --suite stress --out artifacts/llm-smoke-inputs.jsonl
sim-engine compare --scenarios artifacts/llm-smoke-inputs.jsonl --candidate-backend openai-compatible --out artifacts/llm-comparison
```

Start with a handful of users: a model can take up to 12 actions per session, so 100 migrated users can mean up to 1,200
planning calls. `--max-requests` limits requests per invocation and there are no silent retries.

**NOOA harness** (Linux or WSL 2): `pip install -e '.[nooa]'`, `nooa connect`, create an alias, `export SIM_NOOA_MODEL=<alias>`,
then `sim-engine compare ... --candidate-backend nooa`. Pin the NOOA release you inspected.

**Canary and rollback (service desk)**: `sim-engine rollout --db artifacts/rollout.sqlite init|set-percent|route|rollback`, `sim-engine traffic`,
`sim-engine monitor --apply-rollback`. **n8n creator control plane and draft gateway**: `n8n-lab control --db ... init|advance|observe|route|rollback|status`,
`n8n-lab draft` and `n8n-lab serve` (inactive drafts only; set `N8N_LAB_GATEWAY_TOKEN`); `n8n-lab export` writes an importable example without any server:
`n8n-lab export --spec examples/n8n-workflow-creator/requirements.json --out artifacts/incident-workflow.json` (verified 2026-11-18, 8 nodes).
**Feedback loop**: `sim-engine expand-failures`, `sim-engine rate`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| n8n editor or fixtures unreachable from the host | Compose network was `internal: true`. Set `internal: false`, `down`, then `up -d --build` |
| Real run: every candidate fails, webhook responses are `404 ... not registered` | Webhook registration lags publish. The adapter retries that 404 for up to 15 s; if you see it, you are running an old `runtime.py` |
| `n8n API ... failed with status 401/403` | Wrong or under-scoped `N8N_LAB_API_KEY`; recreate with workflow and publish scopes |
| Publish call fails on an older n8n that only has the legacy activate endpoints | Set `N8N_LAB_PUBLISH_ACTION=activate` |
| Data Designer: rate limit during health check or generation | Wait a minute and retry; lower `max_parallel_requests`; use `--no-llm`; request a higher quota |
| Data Designer / Nemotron 3.5 returns empty text | It is a reasoning model; thinking is disabled through `chat_template_kwargs.enable_thinking=false` and the token budget is raised. A tiny `max_tokens` yields only reasoning |
| `ModuleNotFoundError: sim_engine` or `No module named pip` | You are in an environment without the project installed. Create `.venv` as in step 1 |
| `FileExistsError` for an output folder | Choose a new `--out`; runs never append to old evidence |
| Gate exit code 2 | Hold, not a failure. Read `gate.json`; small or sparse cohorts can legitimately hold |
| Tests report 2 skipped | Expected: Node.js absent and the opt-in n8n test |
| Cost shows `null` | Pricing not configured; set `SIM_INPUT_USD_PER_MILLION` and `SIM_OUTPUT_USD_PER_MILLION` |
| Canary at 20% gave 10% (or 25%) of flows | Exposure is a tenant hash threshold, not an exact quota; do not re-roll salts |

## Repository map

| Location | Purpose |
|---|---|
| `src/sim_engine/` | Service-desk domain: contracts, scenario sampler, stateful world, agents, memory migration, runner, evaluation and gate, rollout, traffic, feedback, report |
| `src/sim_engine/workflow_lab/` | n8n domain: creator, compiler, fixture services, reference and n8n runtimes, oracle and evaluator, migration controller, gateway, SDG, **mutants, scenarios_dd, certify** |
| `deploy/n8n/` | Dedicated Compose stack for n8n and the fixture service |
| `examples/service-desk/` | Kick-start example: README, `run.sh` (step A in one command), seed scenario used by tests |
| `examples/n8n-workflow-creator/` | Advanced example: README, `run_reference.sh` (step B), `run_certification.sh` (step D), draft request, requirements, importable workflow |
| `scripts/` | `inference_example.py`, `generate_sdg.py`, `enrich_with_data_designer.py` |
| `configs/population.json` | Illustrative (not calibrated) population weights |
| `tests/` | Invariant, SDG, inference and workflow-lab tests (29 passed, 2 skipped) |
| `artifacts/` | Git-ignored run evidence; each run needs a new folder |
