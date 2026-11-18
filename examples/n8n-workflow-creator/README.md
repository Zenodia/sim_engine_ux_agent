# Example 2: n8n workflow creator (advanced)

An AI **creates and revises automation workflows** that really run on a **self-hosted n8n**; independent checks verify the
business effects those workflows produce; and a mutation-testing step measures how good the grader and the test suites are.
Built on the same engine as [Example 1](../service-desk/README.md), with real-engine execution and NVIDIA NeMo Data Designer added.

## The use case

An operations owner asks for an incident automation: take an alert, validate it and strip personal data, create a ticket, notify the
regional channel, and escalate critical incidents once acknowledged. In a later conversation they change the severity threshold, the EU
channel and the acknowledgement rule. The creator must keep the existing project and default channel, ask about an unnamed destination
and apply the *current* requirements rather than stale memory. Then the workflow has to behave: no duplicate tickets on duplicate
delivery, a retry after "ticket committed but returned 503", tenant isolation, and hostile alert text treated as data.

How it is built:

- The model writes a typed `Spec` (`requirements.json` here), never code or URLs. A deterministic compiler emits native n8n JSON
  (Webhook, Code, If, HTTP Request nodes); see `incident-workflow.json`, which you can import into any n8n.
- Ticketing and messaging are **fixture APIs** with idempotency, tenant isolation and fault injection, not a live Jira or Slack.
- An **independent oracle** recomputes the expected tickets, notifications and escalations and compares them with the fixture state.
- A **Python reference executor** and a **real n8n executor** run the same workflows. Reference evidence never authorises n8n progression.
- Migration stages (baseline, offline, shadow, canary, expansion, full, rollback) advance only on fresh, release-bound evidence.

## Three levels, from no setup to real engine

### Level 1: reference lifecycle (no keys, no Docker, about 1 minute)

```bash
bash examples/n8n-workflow-creator/run_reference.sh
```

Verified 2026-11-18: offline 100/100, shadow 100/100, canary 10/10 (baseline fails 90/90), expansion 50/50, full 100/100, then
`rollback drill phase: rollback`. The baseline creator is deliberately defective, so it fails every flow it is given. This is the Python
reference only.

### Level 2: verifier certification and failure-driven generation (no keys, no Docker)

```bash
bash examples/n8n-workflow-creator/run_certification.sh                          # 12 template-titled scenarios, reference executor
HARDEN=1 bash examples/n8n-workflow-creator/run_certification.sh                 # ...then targeted variants for every mutant that survived
COUNT=24 LLM=1 HARDEN=1 bash examples/n8n-workflow-creator/run_certification.sh  # Data Designer + Nemotron write the titles (needs NVIDIA_API_KEY)
```

NeMo Data Designer generates scenarios (seeded dimensions, LLM-written titles, a control-validator column). The script runs the known-good workflow and **sixteen
deliberate defects** (threshold off by one both ways, wrong EU channel, inverted acknowledgement, PII leak, no dedupe, wrong project, no retry, no tenant check,
a workflow that obeys a routing directive in the alert title, escalating high, idempotency-key collision, notification before ticket, an EU-only threshold bug,
a US-only acknowledgement skip, a 200-character title limit) against each scenario *and* three fixed suites, and reports blind spots, mutants a suite never exercises,
and which input exposes which defect. With `HARDEN=1`, each surviving or unexercised mutant becomes a targeted, certified variant.

Verified 2026-11-18 (24 LLM-title scenarios, reference **and real n8n**, 1,224 cells each; details in [the overview](../../docs/01-overview.md#verified-results)):

| Result | Value |
|---|---|
| Real n8n versus reference | Identical on every cell: 0 divergences, 0 errors |
| Fixed suites killed (of applicable mutants) | v1 267/272, v2 296/296, v3 345/345 (generated scenarios: 138/215, each is narrow by design) |
| What the loop found | v1 kills the no-retry defect only 4/9 (a duplicate delivery heals the 503); the **oracle** could not see a notification sent before the ticket until an `effect_order` check was added; v1 and v2 never exercised three combination or boundary defects, which v3 now covers |
| `harden` on real n8n | 32 targeted variants (2 per mutant): 32/32 passed their control and killed their mutant on both runtimes; random sampling had killed 33 to 75% of the exposure-limited ones; no suspected oracle gaps |
| Template-title default run (12 scenarios, reference only) | Controls 12/12; fixed v3 kills 166/166; counts vary with the seed |

### Level 3: real self-hosted n8n (Docker, one-time manual setup)

```bash
docker compose -f deploy/n8n/compose.yaml up -d --build      # n8n 2.47.7 on 127.0.0.1:5680, fixtures on 8091
# open http://localhost:5680, create the owner account, then Settings > n8n API > create a key with workflow
# create/read/update/delete and publish scopes; put it in .env as N8N_LAB_API_KEY
n8n-lab generate --count 4 --out artifacts/n8n-integration-tasks.jsonl
n8n-lab evaluate --tasks artifacts/n8n-integration-tasks.jsonl --executor n8n --allow-activation --out artifacts/n8n-runtime-check
EXECUTOR=both HARDEN=1 bash examples/n8n-workflow-creator/run_certification.sh      # certification and hardening on reference and n8n
```

Verified 2026-11-18: rules creator candidate 4/4 and baseline 0/4, identical to the reference on all 8 workflows; live Sonnet creator
(`--creator llm`, needs `SIM_LLM_API_KEY`) candidate 6/6 and baseline 0/6. `--allow-activation` lets the adapter import and temporarily
publish only its own test workflows, call their webhooks and unpublish them again. Full bring-up, remote port-forwarding and
troubleshooting: [setup guide, section C](../../docs/02-setup-and-reproduce.md). Two things to know: the Compose network must be
`internal: false`, and n8n publishes before its webhook is registered (the adapter handles that).

## Files in this folder

| File | What it is |
|---|---|
| `requirements.json` | An example typed `Spec`: project, minimum severity, channels, dedupe, privacy, acknowledgement rule |
| `incident-workflow.json` | The importable native n8n workflow compiled from it. Regenerate: `n8n-lab export --spec examples/n8n-workflow-creator/requirements.json --out artifacts/incident-workflow.json` |
| `draft-request.json` | Request shape for the authenticated draft gateway (`n8n-lab serve` / `draft`); it always creates inactive drafts |
| `run_reference.sh`, `run_certification.sh` | The runnable levels above; both need a fresh output folder |

Code: `src/sim_engine/workflow_lab/` (`creator`, `compiler`, `fixtures`, `runtime`, `evaluate`, `migration`, `gateway`, `sdg`, `tasks`,
`mutants`, `scenarios_dd`, `certify`). Compose stack: `deploy/n8n/`.

## NVIDIA components in this example

NVIDIA inference gateway serving Claude Sonnet (creator under test); Nemotron 3 Super for synthetic conversations; **NeMo Data Designer 1.0.0**
with Nemotron 3.5 Lightning for scenario titles. NOOA, User Sim, Gym, Relay, Helix, Fabric and Agent Memory are not used; see
[future directions](../../docs/03-future-directions.md).

## Limits

Fixture services, not real Jira or Slack; no SSO or RBAC; acknowledgement is an event flag, not a long-running approval; only offline
evidence has run on real n8n (shadow, canary, expansion and full ran on the reference); cost is unknown unless pricing is configured; the mutant
set is ours and the title-injection trigger is a crude lexical proxy; LLM-written titles added little adversarial strength. All evidence is
`scope=fixture` with `production_authorized=false`.
