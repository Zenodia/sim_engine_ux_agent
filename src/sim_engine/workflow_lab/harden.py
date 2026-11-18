"""Failure-driven scenario generation: turn mutants that survived into targeted, certified variants.

A *failure* here is a certification gap: a scenario on which a mutant was applicable but the oracle reported no failed check
(it survived), or a scenario whose events could not exercise the mutant at all. For each failure this module

1. **classifies** why (`classify`): the scenario lacked the input the defect needs (insufficient exposure), or it had that
   input and the mutant *still* survived, which is a suspected oracle gap (this is how the ordering gap behind `notify_first` was found);
2. **generates** a targeted variant: the parent's dimensions with the exposing dimensions forced, produced through the same
   Data Designer seed-dataset path (LLM title, control validator), keeping the parent's lineage (`base_task`, `split`);
3. **re-certifies** the variants (control plus the target mutant) on the chosen runtimes and reports whether targeting kills more
   than random sampling did.

The map `EXPOSURE` is domain knowledge about which input exposes which defect. It is validated empirically by the targeted kill
rate and by the list of survivors that met the requirements; it is not assumed correct.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from sim_engine.evidence import dump

from .certify import run_cell
from .mutants import BY_NAME, MUTANTS
from .scenarios_dd import DIM_VALUES, META, Scenario, generate_scenarios, load_scenarios

# mutant -> dimension values that expose it (typed values; booleans as True/False)
EXPOSURE: dict[str, dict] = {
    "threshold_up": {"probe": "at"},
    "threshold_down": {"probe": "below"},
    "eu_channel_is_default": {"probe": "at", "probe_region": "EU"},
    "ack_flipped": {"companion": "crit_eu_unacked"},
    "pii_leak": {"probe": "at"},
    "no_dedupe": {"probe": "at", "dup_mode": "immediate"},
    "wrong_project": {"probe": "at"},
    "no_retry": {"probe": "at", "fault": "both", "dup_mode": "none"},
    "no_tenant_check": {"distractor": True},
    "title_routes": {"probe": "at", "hostile_style": "directive_json"},
    "escalate_high": {"min_severity": "high", "probe": "at", "probe_ack": True},
    "key_collision": {"min_severity": "critical", "probe": "at", "probe_region": "EU", "companion": "crit_eu_acked"},
    "notify_first": {"probe": "at"},
    "eu_threshold_up": {"probe": "at", "probe_region": "EU"},
    "us_ack_ignored": {"ack_required": True, "companion": "crit_us_unacked"},
    "title_limit_200": {"title_pad": True, "probe": "at"},
}


def classify(mutant: str, scenario: Scenario, exercised: bool = True) -> tuple[str, dict]:
    """Return (cause, missing requirements). cause is `unexercised`, `insufficient_exposure` or `suspected_oracle_gap`."""
    if not exercised:
        return "unexercised", dict(EXPOSURE[mutant])
    missing = {k: v for k, v in EXPOSURE[mutant].items() if scenario.dims.get(k) != v}
    return ("insufficient_exposure", missing) if missing else ("suspected_oracle_gap", {})


def _row(dims: dict, **meta) -> dict:
    row = {k: ("yes" if v is True else "no" if v is False else v) for k, v in dims.items() if k in DIM_VALUES}
    row.update({k: str(v) if v is not None else "" for k, v in meta.items() if k in META})
    return row


def harden(run_dir: Path, scenarios_path: Path, runtimes: list, out: Path, per_mutant: int = 3, use_llm: bool = True,
           seed: int = 0) -> dict:
    import random
    out.mkdir(parents=True, exist_ok=False)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cells = json.loads((run_dir / "cells.json").read_text(encoding="utf-8"))
    primary = summary["primary_runtime"]
    scenarios = {s.scenario_id: s for s in load_scenarios(scenarios_path)}
    index = {(c["runtime"], c["suite"], c["scenario"], c["mutant"]): c for c in cells}
    rng = random.Random(seed)

    # 1. Failures and their classification, on the primary runtime's generated suite.
    failures = defaultdict(list)  # mutant -> [(scenario, cause, missing)]
    before = {}
    for m in MUTANTS:
        applicable = survived = 0
        for sid, s in scenarios.items():
            cell = index.get((primary, "generated", sid, m.name))
            if cell is None:
                cause, missing = classify(m.name, s, exercised=False)
                failures[m.name].append((s, cause, missing))
                continue
            applicable += 1
            if not cell["failed"]:
                survived += 1
                cause, missing = classify(m.name, s)
                failures[m.name].append((s, cause, missing))
        before[m.name] = {"applicable": applicable, "survived": survived, "exercised": round(applicable / len(scenarios), 3),
                          "kill_rate": None if not applicable else round(1 - survived / applicable, 3)}

    # 2. Targeted seed rows: prefer parents on which the mutant survived (exercised), then unexercised ones.
    seed_rows, plan = [], []
    for m in MUTANTS:
        rows = sorted(failures[m.name], key=lambda f: (f[1] == "unexercised", rng.random()))[:per_mutant]
        for parent, cause, missing in rows:
            dims = {**parent.dims, **EXPOSURE[m.name]}
            seed_rows.append(_row(dims, target_mutant=m.name, parent=parent.scenario_id, base_task=parent.base_task, split=parent.split))
            plan.append({"mutant": m.name, "parent": parent.scenario_id, "cause": cause, "missing": missing})
    if not seed_rows:
        result = {"note": "No survivors or unexercised mutants to target", "targets": {}}
        dump(out / "summary.json", result)
        return result
    variants, stats = generate_scenarios(use_llm=use_llm, seed_rows=seed_rows, first_index=5000)
    dump(out / "generation.json", stats)
    (out / "variants.jsonl").write_text("".join(v.model_dump_json() + "\n" for v in variants), encoding="utf-8")

    # 3. Re-certify: control plus the target mutant, generated suite only.
    results = []
    for runtime in runtimes:
        for variant in variants:
            mutant = BY_NAME[variant.target_mutant]
            control = run_cell(runtime, variant, variant.events, None)
            cell = run_cell(runtime, variant, variant.events, mutant) if mutant.applicable(
                variant.spec, variant.events, variant.tenant, variant.faults) else None
            results.append({"runtime": runtime.name, "variant": variant.scenario_id, "parent": variant.parent,
                            "mutant": mutant.name, "control_ok": not control["failed"] and not control["error"],
                            "exercised": cell is not None, "killed": bool(cell and cell["failed"]),
                            "failed_checks": cell["failed"] if cell else [], "error": cell["error"] if cell else None})
        print(f"{runtime.name}: {len(variants)} variants certified", flush=True)
        if runtime.name == "n8n":
            dump(out / "n8n-created-workflows.json", runtime.created)
    dump(out / "cells.json", results)

    # 4. Report: targeted versus random, causes, suspected oracle gaps, lineage, proposed fixed-suite events.
    primary_runtime = "n8n" if any(r["runtime"] == "n8n" for r in results) else results[0]["runtime"] if results else primary
    by_variant = {v.scenario_id: v for v in variants}
    targets = {}
    for m in MUTANTS:
        mine = [r for r in results if r["runtime"] == primary_runtime and r["mutant"] == m.name]
        if not mine:
            continue
        causes = Counter(p["cause"] for p in plan if p["mutant"] == m.name)
        killed = [r for r in mine if r["killed"]]
        targets[m.name] = {"random_before": before[m.name], "variants": len(mine), "exercised": sum(r["exercised"] for r in mine),
                           "killed": len(killed), "targeted_kill_rate": round(len(killed) / len(mine), 3),
                           "causes_before": dict(causes),
                           "suspected_oracle_gaps": [r["variant"] for r in mine if r["exercised"] and not r["killed"]]}
    totals = {"variants": len(results) // max(len(runtimes), 1), "control_ok": sum(r["control_ok"] for r in results if r["runtime"] == primary_runtime),
              "killed": sum(r["killed"] for r in results if r["runtime"] == primary_runtime)}
    lineage_ok = all(v.base_task == scenarios[v.parent].base_task and v.split == scenarios[v.parent].split for v in variants)
    agreement = None
    if len({r["runtime"] for r in results}) == 2:
        pairs = defaultdict(dict)
        for r in results:
            pairs[(r["variant"])][r["runtime"]] = (r["killed"], r["control_ok"], r["exercised"])
        agreement = {"compared": len(pairs), "divergences": sum(len(set(v.values())) > 1 for v in pairs.values())}
    # Fixed-suite gaps (strongest fixed suite on the original run) and a killing variant's events as a proposed addition.
    reference = summary["accepted"]["reference_suite"]
    gaps = {m: v["exercised"] for m, v in summary["suites"][f"{primary}/{reference}"]["per_mutant"].items() if v["exercised"] < 1}
    proposals = {}
    for m in gaps:
        winner = next((r for r in results if r["mutant"] == m and r["killed"] and r["runtime"] == primary_runtime), None)
        if winner:
            proposals[m] = {"variant": winner["variant"], "events": [{k: e[k] for k in ("event_id", "severity", "region", "acknowledged")}
                                                                      for e in by_variant[winner["variant"]].events]}
    result = {"primary_runtime": primary_runtime, "per_mutant_requested": per_mutant, "totals": totals, "targets": targets,
              "lineage_preserved": lineage_ok, "reference_vs_n8n": agreement, "generation": stats,
              "plan_causes": dict(Counter(p["cause"] for p in plan)),
              "fixed_suite_exercise_below_100pct": gaps,
              "fixed_suite_note": "Partial exercise can be a ceiling set by the scenario, not a suite gap: threshold_up cannot apply when the "
                                  "threshold is critical, no_retry needs a fault, us_ack_ignored needs the acknowledgement rule. Compare suites "
                                  "with each other, not with 100%.",
              "proposed_events_for_fixed_suite": proposals}
    dump(out / "summary.json", result)
    write_report(out, result)
    return result


def write_report(out: Path, result: dict) -> None:
    import html
    rows = "".join(
        f"<tr><td>{html.escape(m)}</td><td>{t['random_before']['kill_rate']} (exercised in {t['random_before']['exercised']:.0%})</td><td>{t['targeted_kill_rate']} ({t['killed']}/{t['variants']})</td>"
        f"<td>{html.escape(json.dumps(t['causes_before']))}</td><td>{html.escape(', '.join(t['suspected_oracle_gaps']) or '-')}</td></tr>"
        for m, t in result["targets"].items())
    (out / "report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Failure-driven generation</title>"
        "<style>body{font:16px system-ui;margin:3em}td,th{padding:.5em;border-bottom:1px solid #ccc;text-align:left}</style>"
        "<h1>Failure-driven generation</h1><p>Fixture evidence only. Targeted variants against mutants that survived random sampling.</p>"
        "<table><tr><th>Mutant</th><th>Random kill rate (before)</th><th>Targeted kill rate (after)</th><th>Why parents failed</th>"
        "<th>Suspected oracle gaps</th></tr>" + rows + "</table><pre>" +
        html.escape(json.dumps({k: v for k, v in result.items() if k != "targets"}, indent=2)) + "</pre>", encoding="utf-8")
