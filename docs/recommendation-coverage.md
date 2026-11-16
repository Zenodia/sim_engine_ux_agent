# Initial recommendations: verified coverage and remaining work

Assessment based on the completed **2026-11-16** local run, using the existing
conda-backed Python **3.12.7** `.venv`. This is a coverage record for the original
simulation/evaluation/migration proposal. Checked items mean demonstrated in the
fictional local use case, not validated against real enterprise users or production.

## Successful run snapshot

These results are recorded in versionable documentation so they remain visible after cloning once committed.
Detailed generated artifacts remain ignored by Git.

| Executed workload | Baseline | Candidate / output | Meaning |
|---|---|---|---|
| Focused tests | Not applicable | 11 passed | Regression and boundary checks |
| Dependency consistency | Not applicable | `pip check`: no broken requirements | Existing `.venv` updated successfully |
| Scripted stress comparison, 100 distinct users | 20/100 successful flows | 100/100; zero candidate execution errors or unauthorized attempts | Demonstrates the engineered reference implementations and verifier |
| Release gate on scripted stress run | Paired reference | Eligible for manual review | Configured local gate passed; production authorization stayed false |
| Live Nemotron SDG | Not applicable | 100 users generated; checkpoint resume exercised | Real inference produces reusable synthetic messages |
| Generated-user dataset through rules, 100 users | 60/100 successful flows | 100/100; zero candidate execution errors or unauthorized attempts | Generated messages are consumable by the simulator |
| Local canary replay, 100 flows | 75 assignments; 15 successful flows | 25 assignments; 25 successful flows | 20% tenant-hash exposure produced 25% of this finite flow sample |
| Healthy canary monitor | Not applicable | 25/25 candidate successes; no stop reasons; no rollback triggered | Healthy monitoring path worked |
| Explicit rollback | Not applicable | Controller paused at 0%; fresh session routed to baseline | Manual local recovery path worked |
| Live Sonnet development recheck, two generated users | Rules reference: 1/2 | Sonnet: 2/2; zero execution errors or unauthorized attempts | Live SDK, action loop, tools, memory, and verifier connected successfully |

The final live sample used 10 candidate planning requests in total. Mean candidate
flow duration was approximately 19.8 seconds. Cost is unknown because prices were
not configured; this must not be interpreted as free inference. The two live users
were both in the contractor/German/novice cohort. One exercised preference correction
and timeout-after-commit recovery; the other exercised denial of administrator access.

Generation planned 20 five-user batches, but debugging introduced extra failed and
diagnostic calls. The final resume invocation generated 85 remaining users in 17
requests. The final Sonnet run followed a configuration fix, so it is a development
recheck, not an independent held-out evaluation. Earlier failed runs were retained.

See [local verification](local-verification.md) for fixes and local artifact paths.

## Checked off within the toy implementation

- [x] **Anchor the architecture in a specific use case.** Workspace access across
  two sessions has observable business effects: grants, notifications, and denials.
- [x] **Generate a synthetic user/task population.** Produced 100 users with
  enterprise cohorts, scenario factors, and model-generated message variations.
- [x] **Separate generation from the system under test.** Nemotron generated user
  messages; Sonnet handled the sampled live agent flows. Datasets can be reused.
- [x] **Execute stateful interactions rather than only score static answers.**
  Sessions, clarification, preference updates, tool effects, and retries were exercised.
- [x] **Compare old and new systems under controlled starting conditions.** Both
  arms used isolated environments and memory for the same scenario inputs.
- [x] **Collect outputs and execution evidence.** Events, tool calls/results,
  exposed model output, checkpoints, outcomes, latency, available token usage, and
  model/configuration metadata were written to artifacts.
- [x] **Link evidence to synthetic user context.** Run/scenario/variant identity,
  tenant/user scope, cohorts, and session identity connect records.
- [x] **Keep operational memory separate from evidence storage.** Memory facts and
  execution journals have distinct responsibilities.
- [x] **Test a cross-session memory migration.** v1 facts were converted to v2;
  preference continuity, corrections, snapshots, and reverse conversion were exercised.
- [x] **Verify behavior with independent application-owned checks.** Checked final
  access state, notification destination, permission attempts, completion status,
  clarification, and duplicate mutations. The LLM does not award its own pass.
- [x] **Preserve failure evidence.** The truncated generation and live agent attempts
  remain separate from their successful reruns; rejected SDG responses are now logged.
- [x] **Apply a release gate and show cohort breakdowns.** The scripted stress run
  passed the configured gate with 25 users in each of four cohorts.
- [x] **Exercise stable tenant/session assignments.** Local canary routing, assigned
  flow execution, and the SQLite audit trail were exercised.
- [x] **Exercise explicit rollback and safe session handling.** The local controller
  paused, new sessions returned to baseline, and tests covered draining existing
  candidate sessions instead of silently switching their memory schema.
- [x] **Expose reviewable results.** Portable HTML reports were generated and a
  manual rating record was attached to an episode.

## Partial coverage: do not count these as complete

| Initial recommendation | What was demonstrated | What remains |
|---|---|---|
| Emulate the underlying user base | Fictional cohort weights, behavioral rules, generated messages | Calibration against approved real usage and independent realism review |
| Validate the new LLM system | Two live Sonnet cases passed after fixes | Representative live evaluation across cohorts, repeated trials, and stronger uncertainty estimates |
| Evaluate the full harness/model/memory combination | Rules reference versus direct SDK agent, with local fact schemas | Controlled model/harness ablations and optional NOOA runtime verification |
| Collect and rate outputs | Mechanical outcome scores plus rating attachment | Real UX review, calibrated qualitative scoring, reviewer identity/process, and analysis of disagreements |
| Continuously monitor and roll back | Healthy monitor plus manual rollback; controller safety tests | Inject bad canary outcomes and verify monitor-triggered rollback end to end; operate a real monitoring loop |
| Feed failures into new corner cases | Failure-expansion command ran successfully | That run had zero candidate failures and generated zero mutations; verify actual mutation generation using retained development failures |
| Discover optimization opportunities | Metrics, failed checks, traces, and diagnosed configuration fixes | A measured optimization loop with independent before/after evidence |
| Migrate state and memory | Local fact-schema conversion and scope preservation | Real backends, concurrent writes, version fences, deletion/expiration, larger histories, and reconciliation |
| Track cost and performance | Actual live latency/tokens where available | Pricing configuration, complete cross-run accounting, NOOA usage aggregation, and load/long-duration tests |
| Validate SDG quality | Schema/identity/task-token checks and usable outputs | Full semantic preservation checks, stage yield metrics, diversity/coverage review, and calibrated judges if introduced |

## Not exercised by the completed run

- [ ] Production observation ingestion or a population calibrated to real users.
- [ ] Interactive NeMo User Sim / Nemotron-Personas integration; current live SDG
  paraphrases messages while interactive user behavior remains rule-driven.
- [ ] NeMo Gym, Agent Memory dataset tooling, Relay, Helix, or Fabric SDK integration.
- [ ] The optional NOOA adapter on Linux/WSL 2, or the optional Data Designer SDK path.
- [ ] An independent sealed holdout with novel tasks and no development reuse.
- [ ] Production shadow evaluation with isolated candidate writes and side effects.
- [ ] A real percentage-based enterprise gateway rollout or a multi-step exposure ramp.
- [ ] Recovery of real external actions, production database writes, or active workflows.
- [ ] Production retention/redaction/access-control enforcement for real user telemetry.
- [ ] The proposed n8n workflow-creation domain, which remains deferred as requested.

## Recommended next work, in order

1. **Review the 100 generated users and define live-test coverage.** Check meaning,
   language, permissions, ambiguity, preference changes, and cohort balance. Keep the
   demo at 100 users; a larger count is not the immediate requirement.
2. **Close the two small feedback/control gaps without more inference.** Feed a
   retained failed development episode into failure expansion and verify its new
   tasks; inject a failing canary outcome and assert monitor-triggered rollback.
   Keep these fixtures clearly labeled so they are not mistaken for real user data.
3. **Run a budgeted, stratified live sample.** Cover all four cohorts plus authorized,
   denied, ambiguous, stale-memory, injected-tool-text, and uncertain-write cases.
   Choose a request/token budget before expanding toward all 100 live users. Report
   quality and efficiency separately; do not weaken the gate to force a pass.
4. **Create a genuinely independent holdout.** Use new scenarios or workflow logic,
   freeze versions/settings, and evaluate once after the development fixes. Separate
   cold versus migrated starts and test repeated runs for stochastic variation.
5. **Validate optional components only when needed.** Test NOOA on Linux/WSL 2 using
   the same model and environment for a fair harness comparison. Add User Sim/Gym or
   Data Designer when their capabilities answer a concrete test need. Integration
   of every named NVIDIA component is not required to make the toy useful.
6. **Before any real deployment, add the production layer.** Approved observations,
   telemetry governance, a shadow-safe environment, a schema-aware traffic gateway,
   recoverable tool writes, operational monitoring, and a preplanned rollout are
   prerequisites for interpreting this architecture as a deployment process.

The completed run establishes that the local simulation/evidence/control plumbing
and both supplied inference routes work together. It does not establish production
readiness, population realism, or superiority of one model/harness/memory system.
