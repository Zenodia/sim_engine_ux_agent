# Manual remote run notes

No checks below were executed during authoring.

1. Use a clean remote checkout, Python 3.12/3.13, and Linux/WSL 2 for NOOA.
2. Install the core package and inspect the CLI with `sim-engine --help`.
3. Run a small rules comparison with a new output folder. Inspect event order,
   memory snapshots, final grants/notifications, and deterministic outcomes.
4. Run the focused invariant tests if desired. They cover write timeout retries,
   authorization enforcement, memory conversion/isolation, combined stress, and
   session draining on rollback. They do not make network calls.
5. Configure the model endpoint/NOOA alias and inspect the selected package versions.
   Generate a lockfile or freeze the environment for the experiment before recording results.
6. Start with a few actual model episodes. Inspect errors, exposed requests/responses,
   and native NOOA journals before larger runs. Do not assume SDK compatibility based
   solely on the code having been authored against upstream examples.
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
- JSON-output errors: confirm the endpoint supports Chat Completions JSON mode and the
  selected model follows the action contract. Invalid outputs remain failed episodes.
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
