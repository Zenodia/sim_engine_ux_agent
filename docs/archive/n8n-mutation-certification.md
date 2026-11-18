# Verifier certification by mutation testing (Data Designer + real n8n)

Question answered: **how good is the final-effect oracle, and how good is a test suite, at catching
defective incident workflows?** Fixture scope only; `production_authorized=false`.

## How it works

1. `scenarios-dd`: NeMo Data Designer (`data-designer` 1.0.0) samples scenario dimensions (threshold
   position, acknowledgement rule, confusable channel names, fault type, duplicate placement, cross-tenant
   distractor, companion events, hostile-title style). An LLM column (`DATA_DESIGNER_MODEL`, thinking disabled
   through `extra_body`) writes only the free-text alert title. Events are then built deterministically. A local
   validator column rejects any scenario on which the known-good workflow fails the oracle on the reference
   executor. Expected outcomes always come from `evaluate.verify_effects`, never from a model.
2. `certify`: for every scenario, run the known-good control and each applicable **mutant** (8 deliberate
   defects in `mutants.py`: threshold off by one in both directions, EU channel wrong, acknowledgement inverted,
   PII leak, no dedupe, no retry, no tenant check) on the reference executor and real n8n. A mutant is
   *killed* when the oracle reports at least one failed check. Mutants with no possible observable effect
   (equivalent) are skipped, not counted as survivors. The legacy fixed 10-event suite is run on the same specs for a paired comparison.
3. Reference and n8n results are compared cell by cell.

```bash
python -m sim_engine.workflow_lab.cli scenarios-dd --count 24 --out artifacts/mutation-cert/scenarios-24.jsonl
python -m sim_engine.workflow_lab.cli certify --scenarios artifacts/mutation-cert/scenarios-24.jsonl \
  --executor both --allow-activation --out artifacts/mutation-cert/run-24     # use --executor reference for no n8n
```

Needs `NVIDIA_API_KEY`, `DATA_DESIGNER_MODEL`, `DD_END_POINT` in `.env` (use `--no-llm` for template titles and no
inference). `--executor n8n|both` needs the dedicated stack and `N8N_LAB_API_KEY`.

## Result (2026-11-18, 24 scenarios, 411 cells per runtime, 9 mutants)

| Suite | Controls pass | Mutants killed | Notes |
|---|---|---|---|
| Legacy fixed 10 events | 24/24 | 189/198 (95.5%) | `no_retry`: only 4/13 |
| Generated, per scenario | 24/24 | 90/165 (54.5%) | each scenario is deliberately narrow; `no_retry` 7/13 |

- **Real n8n and the reference agree on all 411 cells (0 divergences)**, with no cell errors and 0 active workflows left afterwards.
- **Real finding:** the legacy suite delivers its first event twice back to back. The duplicate delivery silently
  repairs the transient 503, so a workflow with **no retry passes** in 9 of 13 cases. Generated scenarios that
  fault without a masking duplicate catch it.
- **Acceptance rule (tightened):** a scenario is accepted only if the control passes on every runtime *and* it kills a
  mutant that the legacy suite, run on the same spec, misses. Result: **3 of 24 accepted** (all `no_retry`; 2 train, 1 holdout),
  although all 24 kill something. The earlier "any kill" rule accepted all 24 and filtered nothing.
- **Redundancy:** two scenarios (`scn-0013`, `scn-0021`) already reproduce every mutant type the generated suite can kill.
  Most of the 24 add no new mutant type; their value is attribution and varied inputs.
- **Title-sensitive mutant (`title_routes`):** a workflow that obeys instructions in the alert title (trigger: the title
  contains "ignore", a URL or a `"channel"` key). The legacy suite always kills it (its injected-title event); generated
  scenarios kill it 5/8 times, only where the title triggers.

### Do LLM-written titles add value?

| Style | Titles that trigger the pattern: LLM | Template |
|---|---|---|
| benign | 0/8 | no |
| instruction_injection | 3/3 | yes |
| embedded_json | **0/7** | yes |
| long_markdown | 5/6 (mostly incidental) | no |

Conclusion: weak and uneven. The LLM's "embedded JSON" titles were harmless status JSON and never carried the
`"channel"` key; its `long_markdown` titles matched mainly through incidental words ("ignored by design") or a URL, not
real injection attempts. Deterministic templates hit the trigger more reliably. The LLM adds natural-language variety,
not adversarial strength, and the trigger pattern is a crude lexical proxy for "obeys injected instructions".

## Bug found while doing this

The `embedded_json` template used `str.format` and raised `KeyError` on its literal JSON braces, so in `--no-llm`
mode (or after an empty LLM title) those scenarios would have been silently rejected by the validator. Fixed with a
plain replace and covered by a test over all template styles.

## Honest limits

- The generated suite beats the legacy suite only on `no_retry`; its per-scenario kill rate is lower.
- Mutants are ones we authored, so a high kill rate shows detection of known defect classes, not completeness.
  The oracle and the scenario builder share one reading of the spec, so a shared misreading would go unseen.
- `title_routes` uses a lexical trigger, so incidental matches count as kills.
- Zero reference/n8n divergence supports the reference executor for these mutants; it found no n8n-only defect on this family.
- The build.nvidia.com endpoint rate-limited heavily (many 429s; Data Designer retried automatically), so title
  generation for 24 rows took a few minutes. Larger runs need a higher quota or `--no-llm`.
- Each n8n cell imports a draft; the lab instance accumulates unpublished `sim-engine:*` drafts (ids in `n8n-created-workflows.json`). Clean them up in the editor if desired.
- Data Designer sampling is not seeded here; `scenarios.jsonl` is the reproducible record.
