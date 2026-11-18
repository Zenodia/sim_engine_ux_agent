# Workflow-creator validation: 2026-11-16

Validated locally in the existing conda-backed Python 3.12.7 `.venv`. The original
service-desk tests remain in the suite. The native n8n engine was subsequently run on
2026-11-18 (self-hosted n8n 2.47.7 in Docker); see
[Real n8n engine check](#real-n8n-engine-check-2026-11-18).

## Executed results

| Check | Observed result |
|---|---|
| Full test suite | **25 passed, 1 skipped** |
| Dependencies | `pip check`: no broken requirements |
| n8n node schemas | Representative Webhook, Code, If and HTTP Request configurations validated by official n8n tooling |
| Compiled JavaScript | Executed with Node.js in a test; scope, privacy, acknowledgement and hostile-title behavior passed |
| Offline reference comparison | Candidate **100/100**, zero execution errors |
| Shadow reference comparison | Candidate **100/100**, isolated from the baseline |
| Canary at configured 20% tenant-hash exposure | Candidate **10/10**; baseline received the other 90 flows |
| Expansion at configured 50% exposure | Candidate **60/60**; baseline received the other 40 flows |
| Full fixture exposure | Candidate **100/100**, zero execution errors |
| Recovery drill | Controller latched at rollback/0%; a new session routed to baseline |
| Live Sonnet creator | **4/4** revised workflows passed reference event verification, across all four declared cohorts; **5** planning/clarification requests |
| Live Nemotron workflow SDG | **4** conversations generated in **1** request and accepted by reference contract checks |
| Generated SDG conversations through reference execution | Candidate **4/4** |

Tenants contain multiple users. Exposure is a hash-space threshold, not an exact
flow quota, so 20% and 50% produced 10% and 60% of these finite samples. Session
assignments remain stable within a window. New observation windows use new session
IDs, allowing later sessions to follow increased tenant exposure.

The rules baseline is deliberately defective: it retains old EU/acknowledgement
requirements, has legacy deduplication behavior and lacks the candidate's retry path.
Every generated task exercises a revision plus duplicate deliveries, so all baseline
flows failed at least one behavior check. These are controlled defect-detection
results, not evidence that a particular production system or model is inferior.

## What is checked off from the original lifecycle

- [x] A second, concrete domain: enterprise incident-workflow creation and revision.
- [x] Native, versioned n8n workflow JSON with a committed importable example.
- [x] Synthetic creator users plus business-event simulation as separate layers.
- [x] Cross-session memory conversion, scope preservation and requirement correction.
- [x] Independent checks of tickets, notifications and escalations, not JSON validity alone.
- [x] Retries, duplicate delivery, privacy minimization, tenant boundaries and untrusted data.
- [x] Baseline/offline/shadow/canary/expansion/full/rollback control flow in fixture scope.
- [x] Fresh-window and release/runtime-bound evidence; artifact/outcome integrity checks.
- [x] Configurable latency and cost limits; unknown pricing fails a configured cost gate.
- [x] Actual HTTP creator gateway authentication and draft generation tested locally.
- [x] Incoming shadow messages copied into separate candidate conversation/memory stores.
- [x] Automatic rollback on failed candidate observations and candidate-session draining,
  verified in tests; the successful lifecycle run used a manual recovery drill.
- [x] Actual self-hosted n8n import -> publication -> webhook execution -> unpublication
  (4 users, rules creator; see the real-engine section below).
- [x] Both supplied inference models exercised with small live workflow-domain samples.

## Real n8n engine check (2026-11-18)

Dedicated Compose stack, n8n 2.47.7, rules creator, 4 users x (baseline, candidate),
10 deliveries each, `--executor n8n --allow-activation`.

| Check | Observed result |
|---|---|
| Candidate on real n8n | **4/4** passed, zero execution errors |
| Defective baseline on real n8n | **0/4** passed (expected defects detected) |
| Real n8n vs Python reference | Identical pass/fail and identical failed-check sets for all 8 workflows |
| Opt-in pytest integration test | 1 passed |
| Cleanup | All created workflows unpublished; 0 active workflows left |
| Candidate mean latency | about 1.3 s per flow (10 events) |

Findings from the first real run, both fixed:

- **Compose network.** `internal: true` made the published host ports unreachable; it is
  now `internal: false` (ports remain bound to 127.0.0.1).
- **Webhook registration lag.** The publish API returns before the webhook is
  registered, so the first 4-6 deliveries got `404 ... not registered` and every
  episode failed. The adapter now retries only that specific 404 (the workflow never
  ran, so no effect can be duplicated) for up to 15 s; workflow 5xx responses are never
  retried. A unit test covers this. Without it the real-engine result is wrong, so the
  earlier 0/4 run is an adapter defect, not a compiler defect.

Live creator on real n8n (2026-11-18, `--creator llm --executor n8n --allow-activation`,
6 users, 10 deliveries each): candidate **6/6** passed, baseline **0/6**, zero execution
errors, 0 active workflows left afterwards. Mean candidate latency about 8 s per flow
(dominated by model authoring); about 0.7-1.5k input / 0.35-0.7k output tokens per
user; cost unknown because pricing is not configured, so this cannot promote under a
cost gate. The release identity differs from the rules release.

Limits: 4 rules users and 6 live-creator users only; rules-created workflows only; the live Sonnet creator has not yet
been combined with the n8n executor; the Node.js compile test is skipped on this host
(no Node.js), though the compiled Code nodes did execute inside n8n. Evidence remains
`scope=fixture`, `production_authorized=false`.

## Still not checked off

- [ ] Production shadow traffic or a deployed real-enterprise creator migration.
- [ ] Real Jira/Slack/other business effects, end-user SSO/RBAC, or production secrets handling.
- [ ] User approval and deployment of real generated workflows; the gateway saves inactive drafts.
- [ ] An independent held-out evaluation, realistic population calibration or UX study.
- [ ] Long-running acknowledgement/timer workflows and delayed production outcomes.
- [ ] NOOA/Gym/Relay/Helix/Fabric integration for this domain, or arbitrary n8n graph generation.

The controller's `full` phase means all new assignments in a **fixture experiment**.
Every evidence record retains `scope=fixture` and `production_authorized=false`.
The source fingerprint is a local integrity/reproducibility aid, not a signed
attestation or a substitute for dependency pinning and trusted release provenance.

## Evidence on the validation machine

```text
artifacts/n8n-lifecycle-verified-20261116/
  offline/report.html
  shadow/report.html
  canary/report.html
  expansion/report.html
  full/report.html
  full-migration.json
  rollback.json
  migration.sqlite

artifacts/n8n-live-creator-20261116/
  evaluation/report.html
  evaluation/evidence.json
  tasks-sdg.jsonl
  tasks-sdg.sdg.json
  sdg-reference-check/report.html
```

The 100-user reference release identity recorded in the completed run is
`incident-creator-v1:b0332f74e4caf94dad393140dd1389d62c26109eee92e0be57b7b9c026bc7ebc`.
The live creator has a different release fingerprint because its backend/model
configuration differs. Its four successful observations are below the default
promotion minimum of five; they are a connectivity/behavior smoke test, not a
promotion decision. Pricing was not configured for the live model, so cost is unknown.

Raw artifacts remain ignored; this Markdown result snapshot can be committed.
The first reference experiment was retained separately while the completed metric
and full-exposure checks were added. The final paths above refer to the completed run.

## Next step

Scale the live-creator/n8n run beyond six users, configure pricing, and add held-out
tasks. Only after that should live-sample coverage, held-out tasks and actual
enterprise connectors be expanded.
