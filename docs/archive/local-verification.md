# Local verification: 2026-11-16

Executed in the existing Windows `.venv`, backed by conda Python **3.12.7**.
The missing OpenAI SDK, dotenv, and pytest dependencies were installed using
`python -m pip install -e '.[dev]'`. `pip check` reported no broken requirements.

See [initial recommendation coverage and remaining work](recommendation-coverage.md)
for the checked-off items, partial coverage, and prioritized follow-up plan.

## Results

| Check | Result |
|---|---|
| Focused unit/regression suite | 11 passed |
| 100-user deterministic stress comparison | Candidate 100/100 success; no candidate execution errors or unauthorized attempts |
| Local release gate on that stress run | Eligible for manual review; no production authorization |
| Reports, manual ratings, failure expansion, memory conversion | Executed successfully |
| Tenant canary replay, monitor, rollback, post-rollback routing | Executed successfully |
| Live Sonnet connectivity/authentication | Passed |
| Live Nemotron SDG | Generated all 100 users; completed batches persisted and resume exercised |
| Generated SDG dataset through the rules simulator | Candidate 100/100 success; no candidate execution errors or unauthorized attempts |
| Live Sonnet candidate on two generated user flows | Final rerun 2/2 success; no execution errors or unauthorized attempts |

The live agent sample included an allowed request with a preference change and a
write timeout after commit, and a denied administrator-access request. This is a
smoke test of the actual model path, not a 100-user LLM benchmark. Both sampled
users happened to be in the same cohort; this does not establish cohort coverage.
The deliberately defective rules baseline is a demonstration reference.

## Fixes discovered during execution

1. Nemotron generation initially exhausted the 1,024-token output budget. A
   diagnostic request with NVIDIA's documented
   `extra_body={"chat_template_kwargs": {"enable_thinking": false}}` succeeded.
   That setting is now the default for the Nemotron SDG role, and is explicit in
   `.env.example`. See [NVIDIA NIM guidance](https://docs.nvidia.com/nim/large-language-models/2.0.4/turbo/get-started-nemotron-3-super-120b-a12b.html).
2. The model sometimes echoed the supplied `locale` and `expertise`. The parser
   now accepts those known annotations only when they match the source. Changed
   locale/expertise, unexpected fields, changed permission tokens, and invalid
   user identities still fail validation. Regression tests cover the observed shape.
3. A live Sonnet denial response was truncated at 512 output tokens. The candidate
   limit is now explicitly 2,048 in `.env.example` and the tested local `.env`.
   Both original live cases passed on the rerun. The shared 512-token setting and
   SDG's 1,024-token setting remain separate from that candidate override.
4. Every received SDG response is now recorded in an ignored `.requests.jsonl`
   file before validation, preserving diagnostics for truncated/rejected batches.

Generation planned 20 five-user batches. Verification used additional failed and
diagnostic requests while fixing the issues above. Resume preserved the first 15
validated users and generated the remaining 85 in 17 requests. Request budgets
apply per invocation; there are no silent automatic retries.

## Local evidence

Generated artifacts are ignored by Git. On the machine where verification ran:

```text
artifacts/local-verification-20261116-165336/
  rules/report.html                 # 100-user scripted stress run
  rules/gate.json
  canary/report.html
  users-100-sdg.jsonl                # final materialized synthetic user messages
  users-100-sdg.requests.jsonl       # SDG response diagnostics
  sdg-rules/report.html             # all 100 generated users through rules
  live-agent/report.html            # first live attempt, retained with truncation failure
  live-agent-recheck/report.html    # final live 2/2 successful candidate cases
```

The run includes manifests, state/memory snapshots, event journals, manual-review
records and routing audit data. API keys were not printed or copied into evidence.
The existing key stayed in the ignored `.env`.

## Scope limits

The optional NOOA and Data Designer SDK paths were not tested in this run. NOOA's
full supported runtime targets Linux/WSL 2; the local check used the direct SDK
adapter on native Windows. No actual enterprise tool, gateway, or production
memory system was changed. Generated messages passed structural checks; complete
human semantic/realism review remains separate. No claim of production readiness
or model superiority follows from these toy results.
