# 1. Overview: use cases, architecture, NVIDIA components and verified results

`sim_engine_ux_agent` is a **fixture-scale simulation and evidence lab**. It answers one question
for an AI system that acts on a business process: *can we show, with checks that do not trust the
system under test, that a new version is better or safer than the old one before it touches
real users?* Everything here uses fictional data and custom fixture services. Nothing is validated
for production, and every evidence record says so (`scope=fixture`, `production_authorized=false`).

Runnable examples: [service desk (kick-start)](../examples/service-desk/README.md) and
[n8n workflow creator (advanced)](../examples/n8n-workflow-creator/README.md). Related guides: [2. Setup and reproduce](02-setup-and-reproduce.md) and
[3. Future integration directions](03-future-directions.md).

## What the repo does and why it is useful

| Capability | What it gives you |
|---|---|
| Synthetic users and tasks, generated separately from the system under test | Repeatable, labelled test populations; data reusable across runs |
| Stateful, multi-session scenarios with real side effects | Failures that only appear after retries, duplicates, memory changes and revisions |
| An **independent final-effect oracle** | Pass/fail from resulting business state, never from the model's own claim |
| Paired old-versus-new runs in isolated namespaces | Fair comparison; no shared state or contamination between arms |
| Evidence-bound migration (baseline, offline, shadow, canary, expansion, full, rollback) | Exposure only grows on fresh, release-bound evidence; failures latch a rollback |
| Real-engine execution (self-hosted n8n) kept separate from a Python reference executor | You can tell "the design is right" from "the engine really did it" |
| **Verifier certification by mutation testing** (new) | A measurement of how good the grader and each test suite are at catching defective workflows |

The value is in the **loop and its honesty**, not in any single model score: independent checks,
explicit labelling of what kind of evidence each result is, and cheap ways to discover that the
tests themselves are weak. Two findings from real runs show this (details in the results section):

- Running on real n8n exposed a **webhook-registration race** that made every first run fail. The reference
  executor could never have shown that.
- Mutation testing showed the original fixed test suite **cannot detect a workflow with no retry**: its first
  event is delivered twice, and the duplicate silently repairs the transient failure the retry is meant to handle.

## The three worked use cases

### A. Service desk: workspace access with memory continuity (first domain, CLI `sim-engine`)

An analyst states a notification preference in session 1. In session 2 they request workspace access;
the preference may have changed, authorization may be revoked, a tool may return hostile text, and a write
may commit and then time out. The agent must end with exactly one correct grant (or a truthful denial),
exactly one notification on the right channel, and no duplicate mutation, using memory migrated from a legacy
schema. The old rules agent has deliberately engineered defects; the new rules agent is a deterministic reference;
an LLM agent (Sonnet by default) and an optional NOOA harness can be compared against them.

### B. Enterprise n8n workflow creator (second domain, CLI `n8n-lab`)

An operations owner asks for an automation: alert intake, validate and strip personal data, create a ticket, notify
the regional channel, and escalate critical incidents once acknowledged. A later conversation changes the
severity threshold, the EU channel and the acknowledgement rule. The creator must remember the existing project and
default channel, ask about an unnamed destination, and apply current requirements instead of stale memory.

Key design choices:

- The model writes a **typed specification** (`Spec`), not code, URLs or credentials. A deterministic, versioned
  **compiler** turns the spec into native n8n JSON (Webhook, Code, If, HTTP Request nodes). Code nodes hold only
  application-owned logic; all network calls are HTTP Request nodes.
- Ticketing and messaging are **fixture APIs** with idempotency, tenant isolation and bounded fault injection
  (503 after commit, 503 before write). They are integration seams, not claims about Jira or Slack.
- The **oracle** (`evaluate.verify_effects`) recomputes the expected tickets, notifications and escalations from the
  spec and compares them with the resulting fixture state, independently of the generated workflow.
- **Two executors**: a Python reference (offline semantic check, never proof that n8n ran) and a real self-hosted
  n8n adapter (import, publish, call webhook, unpublish, cleanup recorded). Reference-only evidence cannot
  authorise n8n-runtime progression.

### C. Verifier certification by mutation testing (built on B, uses NeMo Data Designer)

The reward or release decision is only as good as the grader. This use case measures that:

1. **Scenario generation with NeMo Data Designer.** Sampler columns vary the scenario dimensions (threshold
   position, acknowledgement rule, confusable channel names, fault type, duplicate placement, cross-tenant
   distractor, companion events, hostile-title style). An LLM column writes only the free-text alert title.
   A local validator column rejects any scenario the known-good workflow fails. Expected outcomes come from the
   oracle, never from a model.
2. **Mutants.** Nine deliberate defects (`mutants.py`): threshold off by one in both directions, wrong EU channel,
   inverted acknowledgement, PII leak, no dedupe, no retry, no tenant check, and a workflow that obeys instructions
   embedded in the alert title.
3. **Certification run.** Every scenario, plus the legacy fixed 10-event suite on the same spec, is executed for the
   known-good control and each applicable mutant on both the reference and real n8n. A mutant is *killed* when the
   oracle reports a failed check. Equivalent mutants are skipped. Results are compared cell by cell across runtimes.
4. **Acceptance.** A scenario is accepted only if the control passes everywhere and it kills a mutant the legacy
   suite misses; a greedy minimal covering subset is reported.

## Architecture

```mermaid
flowchart TD
    USERS["Synthetic users and changing requirements"] --> GW["Draft gateway (inactive drafts only)"]
    GEN["Task / scenario generation<br/>rules, Nemotron SDG, Data Designer"] --> EVAL["Evaluator: offline / shadow / canary"]
    GW --> ROUTE["Evidence-bound creator selection"]
    ROUTE --> OLD["Legacy creator + v1 memory"]
    ROUTE --> NEW["Rules or Sonnet creator + migrated scoped memory"]
    OLD --> SPEC["Typed incident Spec"]
    NEW --> SPEC
    EVAL --> SPEC
    SPEC --> COMP["Deterministic compiler (+ optional mutation)"]
    COMP --> WF["Native n8n workflow JSON"]
    WF --> REF["Python reference executor"]
    WF --> N8N["Dedicated self-hosted n8n"]
    REF --> FIX["Isolated fixture namespaces<br/>tickets, notifications, escalations"]
    N8N --> FIX
    FIX --> ORACLE["Independent final-effect oracle"]
    ORACLE --> EVID["Release-bound evidence, reports"]
    EVID --> CTRL["Migration controller<br/>offline, shadow, canary, expansion, full"]
    CTRL --> ROUTE
    EVID --> MON["Quality, latency, cost checks"]
    MON --> RB["Latched rollback + session drain"]
    RB --> ROUTE
    ORACLE --> CERT["Mutation certification<br/>kill matrix, blind spots, acceptance"]
    GEN --> CERT
```

Generated workflow graph:

```mermaid
flowchart LR
    W["Webhook"] --> P["Code: validate and minimize"]
    P --> V{"Eligible incident?"}
    V -->|yes| T["HTTP: ticket"]
    T --> N["HTTP: notification"]
    N --> A{"Escalation required?"}
    A -->|yes| E["HTTP: escalation"]
    E --> R["Execution receipt"]
    A -->|no| R
    V -->|no| R
```

Design principles that recur in the code:

- **Independent oracle.** The grader checks effects in fixture state; the system under test never grades itself.
- **Typed, bounded authoring.** No model-generated JavaScript or endpoint is ever executed.
- **Isolation.** Fresh namespaces, memory and state per arm and scenario; tenant binding enforced server-side.
- **Evidence labelling.** Reference, n8n, fixture and production evidence are never conflated.
- **Fail closed.** Unknown cost blocks promotion; a failing candidate observation latches rollback; unknown
  release, runtime or scope changes require fresh evidence.

## NVIDIA components and other technology used

| Component | Role here | Status |
|---|---|---|
| **NVIDIA inference gateway** (`inference-api.nvidia.com/v1`) serving Claude Sonnet | Agent / creator under test (OpenAI-compatible Chat Completions) | **Verified live**: service desk (2026-11-16) and the n8n creator on real n8n (2026-11-18) |
| **Nemotron 3 Super** via the same gateway | Batched synthetic-user message variation (SDG) | **Verified live**: 100 service-desk users (2026-11-16); small workflow-domain sample |
| **NeMo Data Designer 1.0.0** with **Nemotron 3.5 Lightning 30B-A3B** via `integrate.api.nvidia.com` | Scenario generation and title writing for certification (thinking disabled with `chat_template_kwargs`) | **Verified live** (2026-11-18): 24 scenarios with LLM titles; deterministic `--no-llm` path also verified |
| **NOOA** (NVIDIA-NeMo labs-OO-Agents) | Optional swappable harness for the service-desk agent | Adapter implemented, **not executed** |
| Older Data Designer script (`scripts/enrich_with_data_designer.py`) | Optional service-desk paraphrase | Implemented, **not executed** |
| NeMo User Sim / Nemotron-Personas, NeMo Gym, Agent Memory, Relay, Helix, Fabric | Extension paths only | **Not integrated**; see [future directions](03-future-directions.md) |
| n8n 2.47.7 (self-hosted, Docker Compose), Docker 29.10 | Real workflow engine for execution | **Verified** (2026-11-18) |

NVIDIA's Agent Toolkit is deprecated upstream (end of life at year end 2026), so this project deliberately
adds no dependency on it.

## Verified results

Environment for the runs below: Linux VM, Python 3.12.16 (`uv` virtualenv), Docker 29.10.0, self-hosted n8n
2.47.7 in Docker Compose, `data-designer` 1.0.0. Generated evidence lives under the git-ignored `artifacts/`;
the numbers here are the durable record. "Re-run" means executed again during this documentation pass.

### Test suite

29 passed, 2 skipped. The skips are the Node.js compile test (Node.js is not installed on the VM) and the opt-in
real-n8n integration test (it passed when enabled earlier on 2026-11-18 and is run with `N8N_LAB_RUN_INTEGRATION=1`).

### A. Service desk, deterministic rules (re-run, zero inference)

| Measure | Result |
|---|---|
| Distinct users, two sessions each | 100 |
| Legacy baseline successful flows | 20/100 (53 safety failures: stale permission trusted, no live policy check) |
| New candidate successful flows | 100/100, zero execution errors, zero unauthorized attempts |
| Release gate (fixed-look Hoeffding, Bonferroni) | `eligible_for_manual_review`; production promotion not authorized |

Earlier on 2026-11-16, recorded but not re-run today: Nemotron generated 100 users in checkpointed batches with
resume; the generated set passed 100/100 through the simulator; live Sonnet passed 2/2 generated flows after fixes
(a truncated denial response led to raising the candidate output limit to 2,048 tokens); a local canary assigned 25
of 100 flows to the candidate (all passed); an explicit rollback routed a fresh session back to baseline. Only
two live-model flows were checked, not 100. See `docs/local-verification.md` and `docs/recommendation-coverage.md`
(historical snapshots).

### B. n8n workflow creator, reference lifecycle (re-run, zero inference, about 51 s)

| Stage | Candidate | Baseline |
|---|---|---|
| Offline | 100/100 | 0/100 (all fail at least one check; the baseline is deliberately defective) |
| Shadow | 100/100 | 0/100 |
| Canary (20% tenant-hash exposure) | 10/10 | 0/90 |
| Expansion (50%) | 50/50 | 0/50 |
| Full fixture exposure | 100/100 | none assigned |
| Recovery drill | controller latched at rollback; a new session routes to baseline | |

Exposure is a hash-space threshold, so the realised flow share differs from the configured percentage and varies
between runs with fresh session IDs.

### C. Real self-hosted n8n (2026-11-18)

| Run | Result |
|---|---|
| Rules creator, 4 users, 10 events each | Candidate **4/4**, baseline **0/4**; mean candidate latency about 1.3 s per flow |
| Real n8n versus reference | Identical pass/fail and identical failed-check sets on all 8 workflows |
| Opt-in pytest integration test | 1 passed |
| Live Sonnet creator, 6 users | Candidate **6/6**, baseline **0/6**, all four cohorts; mean latency about 8 s per flow (model authoring dominates); 0.7 to 1.5k input and 0.35 to 0.7k output tokens per user; cost unknown (pricing not configured) |
| Cleanup | All created workflows unpublished; 0 active workflows after each run |

Two failures were found and fixed on the way, which is the point of running the real engine:

1. The Compose network was `internal: true`, which makes published host ports unreachable. It is now `internal: false`
   (ports remain bound to 127.0.0.1).
2. Publishing returns before n8n has registered the webhook, so the first 4 to 6 events of each run returned
   `404 webhook not registered` and every candidate failed. The adapter now retries only that specific 404 for up to
   15 seconds. This is safe because a 404 means the workflow never ran; workflow 5xx responses are never retried.

The compiled Code nodes executed inside n8n's JavaScript task runner and the injected 503 faults were visible in n8n's logs.

### D. Verifier certification by mutation testing (2026-11-18)

24 Data Designer scenarios, 9 mutants, 411 executed cells per runtime, on both the reference and real n8n.

| Suite | Controls pass | Mutants killed | `no_retry` |
|---|---|---|---|
| Legacy fixed 10 events | 24/24 | 189/198 (95.5%) | **4/13** |
| Generated scenarios, per scenario | 24/24 | 90/165 (54.5%) | 7/13 |

- **Real n8n and the reference agree on all 411 cells** (0 divergences, 0 cell errors, 0 workflows left active).
- **Acceptance** (control passes everywhere and a novel kill versus the legacy suite): **3 of 24**, all `no_retry`.
  The earlier "any kill" rule accepted all 24 and filtered nothing. Two scenarios already reproduce every mutant type
  the generated suite can kill.
- **Blind spot found:** the legacy suite misses `no_retry` in 9 of 13 applicable cases because its first event is
  duplicated back to back, and the duplicate heals the transient 503.
- **Title-sensitive mutant:** legacy kills it 24/24 (its injected-title event always triggers it); generated scenarios
  kill it 5/8, only where the title triggers.
- **LLM-written titles add little adversarial strength.** Instruction-injection titles triggered the pattern 3/3, but
  "embedded JSON" titles were harmless status JSON (0/7 versus always for the template), and "long markdown" titles
  triggered 5/6 mostly through incidental words ("ignored by design") or a URL. The trigger is a crude lexical proxy.
- **Bug found and fixed while writing this:** the `embedded_json` template used `str.format` and failed on its literal JSON
  braces, which would have silently rejected those scenarios in `--no-llm` mode.
- **Rate limiting:** the build.nvidia.com endpoint returned many HTTP 429 responses (Data Designer retried automatically),
  so generating 24 titles took a few minutes.
- Per-scenario kill rate is lower than the legacy suite's by design: each scenario is narrow. The gain is coverage of a
  blind spot and attribution of which input exposed which defect, not a higher overall rate.

### What was not verified

- 100-user live-model runs, held-out tasks, or independent holdouts.
- Shadow, canary, expansion and full stages on **real n8n**; they were exercised on the reference executor only.
- Real Jira, Slack or other enterprise connectors, SSO/RBAC, long-running acknowledgement or timers, production traffic.
- NOOA, User Sim, Gym, Relay, Helix, Fabric, Agent Memory.
- Cost: pricing was not configured, so cost is unknown and cannot pass a cost gate.
- Completeness of the mutant set: mutants are ones we wrote, and the oracle and scenario builder share one reading
  of the spec, so a shared misreading would go unseen.

## Where things are

| Need | Location |
|---|---|
| Step-by-step reproduction | [02-setup-and-reproduce.md](02-setup-and-reproduce.md) |
| Roadmap and open integrations | [03-future-directions.md](03-future-directions.md) |
| Service-desk code | `src/sim_engine/` (`contracts`, `scenarios`, `world`, `agents`, `memory`, `runner`, `evaluation`, `rollout`, `traffic`, `feedback`, `report`) |
| n8n-domain code | `src/sim_engine/workflow_lab/` (`creator`, `compiler`, `fixtures`, `runtime`, `evaluate`, `migration`, `gateway`, `sdg`, `tasks`, `mutants`, `scenarios_dd`, `certify`) |
| Runnable examples with their own READMEs | [`examples/service-desk/`](../examples/service-desk/README.md) (kick-start, use case A) and [`examples/n8n-workflow-creator/`](../examples/n8n-workflow-creator/README.md) (advanced, use cases B and C) |
| Importable example workflow | `examples/n8n-workflow-creator/incident-workflow.json` |
| Compose stack | `deploy/n8n/compose.yaml` |
