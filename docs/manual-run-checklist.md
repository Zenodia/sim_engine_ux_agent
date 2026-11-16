# Manual remote run notes

The core workflow has since been verified locally on Windows; see
[the verification results](local-verification.md). Use this checklist to reproduce
the run on another machine and validate optional integrations separately.

1. Use a clean remote checkout, Python 3.12/3.13, and Linux/WSL 2 for NOOA.
2. Install the core package and inspect the CLI with `sim-engine --help`.
3. Run a small rules comparison with a new output folder. Inspect event order,
   memory snapshots, final grants/notifications, and deterministic outcomes.
   The default toy size is 100 users and the rules backend makes no inference calls.
   Optional `scripts/generate_sdg.py` generates text for 100 users in 20 five-user
   requests, with no automatic retry and checkpoints for explicit resume.
4. Run the focused invariant tests if desired. They cover write timeout retries,
   authorization enforcement, memory conversion/isolation, combined stress, and
   session draining on rollback. They do not make network calls.
5. Update dependencies with `python -m pip install -e .`. Put the key in `.env` at
   the repository root; it loads automatically unless an exported variable overrides it.
   The direct adapter defaults to `https://inference-api.nvidia.com/v1` and
   `aws/anthropic/bedrock-claude-sonnet-5`. Configure the NOOA alias independently
   when using that backend and inspect the selected package versions.
   Generate a lockfile or freeze the environment for the experiment before recording results.
6. Start with a few actual model episodes. Inspect errors, exposed requests/responses,
   and native NOOA journals before larger runs. Do not assume SDK compatibility based
   solely on the code having been authored against upstream examples.
   User count is not API-call count: a model can take up to 12 planning actions in
   each session. Keep SDG generation and agent evaluation budgets separate.
7. Compare complete paired cohorts. A held gate or unknown cost is evidence to
   investigate, not an instruction to weaken limits until the gate passes.
8. Exercise canary routing with a passing local gate and inspect tenant assignments.
   Test a rollback: an existing candidate session must drain, a new session must use
   baseline, and increasing exposure must remain disabled in the rolled-back database.
9. Add manual ratings and generate new development scenarios from observed failures.
10. Keep final holdout tasks apart from optimization. Collect genuine user and
    operational evidence before connecting any real gateway or production tool.

## Troubleshooting without hiding failed observations

- `KeyError`/configuration failure for a backend: set the required environment variables
  or NOOA alias. The episode error record deliberately excludes provider response bodies
  and secrets. For provider failures, use the approved provider's local diagnostics.
- JSON-output errors: confirm the selected model follows the action contract. JSON mode
  is off by default for the supplied NVIDIA example. Set
  `SIM_LLM_RESPONSE_FORMAT=json_object` only if the endpoint supports that option.
  Increase `SIM_LLM_MAX_TOKENS` if completion is truncated. Invalid outputs remain
  failed episodes.
- `FileExistsError` for a run: choose a new output folder. The runner avoids mixing runs.
- Hold gate: read `gate.json`, cohort counts, and failed checks. Fixed-look uncertainty
  may be large for small samples, especially within cohorts.
- All-baseline at low exposure: tenant hashing is deterministic, not an exact finite
  percentage quota. Generate more tenants or inspect assignments; do not reroll salts
  until a favored assignment appears.
- Empty failure expansion: no eligible development failures were found. An empty file
  is a useful result but cannot be passed to `compare`.
- `drain` route: reconcile the old candidate session explicitly; use a new session after
  recovery. The lab does not silently transform live state on rollback.
