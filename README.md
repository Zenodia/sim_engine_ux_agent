# sim_engine_ux_agent

A fixture-scale **simulation and evidence lab** for AI systems that act on business processes. It generates
synthetic users and tasks, runs old and new agents in isolated, stateful environments, grades them with an
**independent final-effect oracle**, gates migration on fresh evidence, and (new) measures how good the grader and
the test suites themselves are using **mutation testing**.

Two worked domains: a fictional **service desk** (`sim-engine`) and **enterprise n8n workflow creation** on a
self-hosted n8n (`n8n-lab`), with scenario generation by **NVIDIA NeMo Data Designer** and models served through
the NVIDIA inference gateway. Everything uses fictional data and fixture services: all evidence is `scope=fixture`
and nothing here is validated for production.

## Start with an example

| Example | What it is | Needs |
|---|---|---|
| [**Service desk**](examples/service-desk/README.md) (kick-start) | Old vs new service-desk agent on 100 synthetic users, graded by independent checks, with a release gate. About a minute | Nothing: no keys, no Docker |
| [**n8n workflow creator**](examples/n8n-workflow-creator/README.md) (advanced) | An AI creates and revises incident workflows that run on a self-hosted n8n; independent verification; mutation-testing certification with NeMo Data Designer | Level 1 and 2: nothing. Level 3: Docker and an n8n API key |

Each example has its own README, runnable scripts and verified expected output.

## Read in this order

| Doc | What it covers |
|---|---|
| [1. Overview](docs/01-overview.md) | Use cases, what the repo does and why it is useful, architecture, NVIDIA components, **verified results** and what was not verified |
| [2. Setup and reproduce](docs/02-setup-and-reproduce.md) | Environment bring-up (including real self-hosted n8n), step-by-step runs with expected output, troubleshooting, repository map |
| [3. Future integration directions](docs/03-future-directions.md) | Prioritised roadmap: certification loop, real-engine promotion stages, deeper Data Designer use, connectors, remaining NVIDIA components |

## Results at a glance (verified 2026-11-18 unless noted)

| What | Result |
|---|---|
| Tests | 29 passed, 2 skipped (no Node.js; opt-in real-n8n test, which passed when enabled) |
| Service desk, rules only (100 users) | Baseline 20/100, candidate 100/100; gate `eligible_for_manual_review` |
| n8n creator, reference lifecycle (100 users) | Candidate passes every stage; rollback drill latches; about 51 s, zero inference |
| **Real self-hosted n8n** (n8n 2.47.7) | Rules creator 4/4 vs defective baseline 0/4; live Sonnet creator 6/6 vs 0/6; identical to the reference on all 8 compared workflows |
| **Mutation-testing certification** (24 Data Designer scenarios, 9 mutants, 411 cells per runtime) | Real n8n and reference agree on every cell; the legacy fixed suite kills 189/198 but only 4/13 of the no-retry defect because a duplicate delivery heals the fault; 3 of 24 scenarios accepted under the novel-kill rule |

Two real-engine findings fixed along the way: the Compose network had to be `internal: false`, and n8n publishes before
its webhook is registered, so the adapter now retries only the `404 not registered` response. Details, limits and the
LLM-title finding are in [the overview](docs/01-overview.md#verified-results).

## Quick start (no keys, no Docker)

```bash
uv venv --python 3.12 .venv && uv pip install -p .venv/bin/python -e ".[dev,sdg]"   # or python -m venv + pip
export PATH="$PWD/.venv/bin:$PATH"
pytest -q                                                    # 29 passed, 2 skipped
examples/service-desk/run.sh                                 # Example 1: 20/100 vs 100/100, gate eligible for review
examples/n8n-workflow-creator/run_reference.sh               # Example 2, level 1: reference lifecycle, zero inference
examples/n8n-workflow-creator/run_certification.sh           # Example 2, level 2: mutation-testing certification
```

For the real-n8n runs, live models and mutation certification, follow
[the setup guide](docs/02-setup-and-reproduce.md). Keys live only in the git-ignored `.env` (template: `.env.example`).

## Archive

Earlier, more detailed documents are kept unchanged in [`docs/archive/`](docs/archive/README.md): the service-desk architecture and
evidence contract, the first-run verification record, the original recommendation checklist, the NOOA fit assessment, the
previous README, and the earlier n8n runbook and validation notes.
