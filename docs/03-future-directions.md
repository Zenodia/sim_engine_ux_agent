# 3. Future integration directions

Companion to [1. Overview](01-overview.md) and [2. Setup and reproduce](02-setup-and-reproduce.md). This is a
prioritised list of what to do next, with what exists today, what to add, and what evidence would show it worked.
Items are proposals. Statements about NVIDIA components that this repository does not yet use come from public
documentation read during earlier assessments and have **not** been exercised here; check them against the
installed version before designing around them.

## Priorities at a glance

| # | Direction | Why now | Effort |
|---|---|---|---|
| 1 | Continue the certification loop (harder mutants, learned exposure map, creator-episode failures) | The first loop already found an oracle gap and three suite gaps | Small to medium |
| 2 | Run the promotion stages on real n8n, with cost and held-out tasks | Today only offline evidence has run on the real engine | Medium |
| 3 | Deeper Data Designer use (validators, seeds, rollout ingestion, workflow chaining) | Turns one-off generation into a repeatable pipeline | Medium |
| 4 | Real connectors, identity and long-running semantics | Needed before any claim beyond fixtures | Large |
| 5 | Remaining NVIDIA components (NOOA, User Sim, Gym, Relay, Helix, Fabric, Agent Memory) | Fair harness comparison, trace export, richer users | Medium each, as needed |
| 6 | Evaluation science (calibration, held-out, noninferiority) | Moves from demonstration to defensible claims | Medium to large |

## 1. Close the certification loop (builds on use case C)

**Done (2026-11-18):** 16 mutants including a realistic title-directive mutant and combination or boundary mutants; an oracle gap found and fixed
(`effect_order`); fixed suites v2 and v3 that close the blind spots the loop found; seeded dimensions through a Data Designer seed dataset; a kill-rate-by-dimension
report; failure-driven generation (`harden`) with a classifier, lineage-preserving targeted variants and re-certification on the reference and real n8n
(32/32 targeted kills, 0 divergences, 0 suspected oracle gaps). Results: [overview](01-overview.md#verified-results).

**Next:**

| Next step | Detail | Evidence of success |
|---|---|---|
| Learn the exposure map instead of hand-writing it | `harden.EXPOSURE` (which input exposes which defect) is domain knowledge. Derive candidate rules from the per-dimension kill rates the report already computes and compare with the hand map | Learned and hand maps agree, or the differences reveal map errors |
| Use failed *creator* episodes as a failure source | Today the failures are surviving mutants. Convert failed episodes (`events.jsonl`, `outcome.json`) of the live creator into seed rows and classify them. Public Data Designer documentation describes rollout ingestion; native n8n logs are not a listed format, so they need conversion, and imported traces are not redacted automatically | New accepted scenarios per recurring creator failure class |
| Harder, independent mutants | Idempotency-key reuse with a changed payload, partial-failure ordering, escalation before notification, state-dependent bugs that only appear after N events, and mutants proposed by a model and then vetted. A mutant the oracle cannot kill reveals an oracle gap, which is the point | New gaps found and fixed, each re-measured |
| A genuinely instruction-following title mutant | The directive mutant is a regular expression. Replace it with a workflow variant whose routing step is steerable by title text, for example an LLM-backed classification step | Kills correlate with real injection success, not pattern matching |
| Promote proposals automatically | `harden` already lists, per gap, the events of a killing variant. Merge them into the next fixed suite automatically and re-certify | Fixed suite v4 produced without hand editing |
| Seeded titles and a quota | Dimensions are reproducible; the LLM titles are not. Obtain a higher build.nvidia.com quota or an enterprise-controlled endpoint and pin titles | Identical scenario files from the same seed; no 429 stalls |
| Cost per accepted scenario | Configure pricing and report cost per accepted scenario, not only counts | A cost figure instead of `null` |
| Held-out evaluation of a certified suite | Evaluate certification quality on independent tasks kept out of generation | Kill rates on held-out tasks match development |

Success metrics for this track: defects caught that earlier suites and the oracle missed, certification cost per accepted scenario, and performance of a
certified suite on independent held-out tasks.

## 2. Promotion stages on real n8n, cost and held-out tasks

**Today:** offline evidence on real n8n for 4 rules users and 6 live-creator users. Shadow, canary, expansion and full ran only on the
reference executor. Cost is unknown because pricing was not configured.

- Run the full controller sequence with `--executor n8n` so every stage's evidence is real-engine evidence; scale beyond six live-creator users.
- Configure pricing and `--max-cost-usd`, and add latency limits per complete flow, so a cost gate is enforced rather than null.
- Add an independent held-out task set with frozen versions and settings, evaluated once.
- Exercise automatic rollback on a deliberately failing candidate observation against real n8n, not only the reference.
- Add repeated trials to estimate stochastic variation of the live creator.
- Capacity and failure testing: concurrent webhooks, n8n restarts mid-execution, fixture outages.

## 3. Deeper Data Designer use

| Capability (per public documentation; verify in 1.0.0) | Proposed use |
|---|---|
| Local callable validators and remote validators | Already used for the control check on the reference. Add a remote validator that calls a certification service so acceptance (novel kill) happens inside the pipeline |
| Seed datasets, expressions, dependent structured columns | Generate whole task bundles: formal requirements, fictional workspace state, persona-visible facts and hidden facts, with referential-integrity checks (a clarification answer must name a channel that exists in the simulated workspace) |
| Rollout ingestion (`AgentRolloutSeedSource`) | Failure-driven generation (above) |
| Structured and judge columns | Judge calibration sets: contrastive good and bad conversations with human adjudication before judge scores enter any reward |
| MCP and tool-use columns | A generator that inspects schemas, builds a candidate, runs it in the isolated n8n lab and keeps the interaction trace. Requires an n8n tool adapter; verified traces support supervised warm starts but are not on-policy reinforcement-learning samples |
| Workflow chaining | Staged generate, validate, certify pipeline. The public documentation marks this experimental, so do not depend on it initially |

Keep expected outcomes independent wherever practical (computed by the oracle, not a model), so a model cannot repeat the same
mistake on both sides. Running the library against an enterprise-controlled inference endpoint is supported; keeping data local depends on
endpoint and tool placement, not on synthetic generation alone.

## 4. Real connectors, identity and long-running semantics

Everything today is fixture scope. Before any production claim:

- Real enterprise connectors and credentials (Jira, Slack or equivalents) behind a shadow-safe sandbox with server-owned identity and scope.
- End-user identity (SSO and RBAC). The current gateway token represents a trusted lab operator, not an end user.
- Long-lived acknowledgement and timer semantics. Acknowledgement is currently a boolean in the event, not a human approval flow.
- Cross-version business-state reconciliation, version fences and a recovery process. Rolling back traffic cannot unsend a message or undo an external action.
- Production telemetry governance: redaction, retention and access control for real user data.
- A separately approved workflow publication and recovery process. The gateway saves inactive drafts only.
- Richer authoring families beyond the bounded incident DSL, and arbitrary n8n graph generation under policy.

## 5. Remaining NVIDIA components

| Component | Intended role | First experiment |
|---|---|---|
| NOOA | Swappable agent harness for the service-desk domain | On Linux or WSL 2, compare direct-model planning against NOOA with the same model, policy, inputs and memory. Then compare cold and migrated memory, so harness effects are separated from memory and model effects |
| NeMo User Sim and Nemotron-Personas | Interactive, population-grounded simulated users instead of scripted behaviour plus paraphrase | Add a User Sim domain once environment and verifier behaviour are understood; keep the private-oracle and public-context separation |
| NeMo Gym | Environment rollouts, verifiers and scenario evaluation | Package the n8n lab (scenario, tools, oracle) as a Gym-style environment |
| NeMo Relay | Runtime interception and normalised trace export | Replace the custom JSONL journal export with OpenTelemetry or ATIF-compatible traces, preserving application correlation IDs |
| NeMo Helix | Repeatable evaluation, optimisation and hardening orchestration | Drive certify, generate, harden as a scheduled loop |
| NeMo Fabric | Common harness execution interfaces | Adapter layer so creators and agents are swappable behind one interface |
| Agent Memory datasets and evaluation | Memory-dependent tasks and verifiers, dataset quality and provenance | Replace the lab-owned scoped Memory class only if a comparison with an enterprise memory service is the goal |

The lab's simple scoped memory, journal and controller stay application-owned so different harnesses can be compared fairly.
No new dependency on NVIDIA Agent Toolkit (deprecated upstream, end of life at year end 2026).

## 6. Evaluation science

- **Calibration.** Replace illustrative population weights (`configs/population.json`) with approved aggregate observations; add independent realism and UX review.
- **Judges.** If qualitative scores are added, calibrate them against human adjudication first; keep deterministic effect checks as the primary signal.
- **Statistics.** The gates are explicit fixture acceptance rules, not a noninferiority claim. A real experiment needs its own sampling and power design, delayed outcomes, and tenant clustering. Avoid repeated looks with promote-on-pass.
- **Held-out and adversarial.** Genuinely novel tasks and adversarial environments, not more paraphrases of existing scenarios.
- **Cost and efficiency.** Report quality and efficiency separately; compare reasoning budgets on matched task sets rather than assuming a trade-off.

## Link to reinforcement-learning use of this lab (context, not implemented here)

If these tasks are used to train or select an agent with a verifiable reward, the reward is only as good as the grader.
The certification results above are directly relevant: a suite that cannot see a missing retry would reward workflows that lack one.
This repository does not contain a training loop; verified demonstrations, targeted evaluation packs and certified hidden scenarios are
the pieces it could supply. Generated demonstrations are not valid on-policy samples and must stay labelled apart from policy rollouts.
