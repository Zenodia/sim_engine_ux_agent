"""Verifier certification by mutation testing, run on the reference executor and real self-hosted n8n.

For every scenario the known-good workflow (control) and every applicable mutant are executed against
a suite of events; the independent oracle `verify_effects` decides pass/fail. A mutant is *killed* when the
oracle reports at least one failed check. Three suites are compared on the same expected spec: the original
fixed 10-event suite (`legacy_v1`), its fixed successor (`legacy_v2`) and the generated scenario events.
Reference and n8n results are compared cell by cell.

Reporting distinguishes two coverage gaps: a *blind spot* (the mutant was exercised but never killed, an oracle or
suite weakness) and *never exercised* (no event in the suite can trigger the mutated behaviour).
"""
import html
import json
import re
import time
from collections import defaultdict
from pathlib import Path

from sim_engine.evidence import dump

from .compiler import TITLE_DIRECTIVE_PATTERN
from .evaluate import verify_effects
from .mutants import MUTANTS, Mutant
from .scenarios_dd import Scenario
from .tasks import event_suite, event_suite_v2, event_suite_v3

SUITES = ("generated", "legacy_v1", "legacy_v2", "legacy_v3")
REFERENCE_SUITE = "legacy_v3"  # the strongest fixed suite; "novel" means a kill it does not achieve


def suites_for(scenario: Scenario) -> dict[str, list[dict]]:
    return {"generated": scenario.events, "legacy_v1": event_suite(scenario.tenant), "legacy_v2": event_suite_v2(scenario.tenant),
            "legacy_v3": event_suite_v3(scenario.tenant)}


def run_cell(runtime, scenario: Scenario, events: list[dict], mutant: Mutant | None) -> dict:
    started = time.perf_counter()
    cell = {"failed": [], "error": None, "http": {}}
    try:
        spec = mutant.spec_fn(scenario.spec) if mutant else scenario.spec
        namespace = runtime.create_scope(scenario.tenant, scenario.faults["ticket"], scenario.faults["notification"])
        responses = runtime.execute(spec, namespace, scenario.tenant, events, "candidate",
                                    mutation=mutant.engine if mutant else None)
        checks = verify_effects(scenario.spec, scenario.tenant, events, runtime.snapshot(namespace))
        cell["failed"] = sorted(c.name for c in checks if not c.passed)
        for response in responses:
            key = str(response.get("http_status", response.get("status")))
            cell["http"][key] = cell["http"].get(key, 0) + 1
    except Exception as exc:  # recorded, never counted as a kill
        cell["error"] = type(exc).__name__ + ": " + str(exc)[:200]
    cell["seconds"] = round(time.perf_counter() - started, 2)
    return cell


def certify(scenarios: list[Scenario], runtimes: list, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    cells = []
    total = len(scenarios)
    for runtime in runtimes:
        for position, scenario in enumerate(scenarios, 1):
            for suite, events in suites_for(scenario).items():
                for mutant in [None, *MUTANTS]:
                    if mutant and not mutant.applicable(scenario.spec, events, scenario.tenant, scenario.faults):
                        continue
                    cell = run_cell(runtime, scenario, events, mutant)
                    cells.append({"runtime": runtime.name, "suite": suite, "scenario": scenario.scenario_id,
                                  "mutant": mutant.name if mutant else "control", **cell})
            print(f"{runtime.name}: {position}/{total} {scenario.scenario_id}", flush=True)
        if runtime.name == "n8n":
            dump(out / "n8n-created-workflows.json", runtime.created)
    summary = analyse(scenarios, cells)
    dump(out / "cells.json", cells)
    dump(out / "summary.json", summary)
    write_report(out, summary)
    return summary


def _rate(killed: int, applicable: int):
    return None if applicable == 0 else round(killed / applicable, 3)


def dimension_effects(scenarios: list[Scenario], index: dict, runtime: str) -> dict:
    """Kill rate of each mutant by scenario dimension value (generated suite): which input exposes which defect."""
    effects = {}
    for m in MUTANTS:
        per_dim = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for s in scenarios:
            cell = index.get((runtime, "generated", s.scenario_id, m.name))
            if cell is None:
                continue
            for dim, value in s.dims.items():
                if dim in ("service", "project"):
                    continue
                slot = per_dim[dim][str(value)]
                slot[1] += 1
                slot[0] += bool(cell["failed"])
        effects[m.name] = {d: {v: tuple(c) for v, c in sorted(vals.items())} for d, vals in per_dim.items()}
    return effects


def analyse(scenarios: list[Scenario], cells: list[dict]) -> dict:
    runtimes = sorted({c["runtime"] for c in cells})
    primary = "n8n" if "n8n" in runtimes else runtimes[0]
    index = {(c["runtime"], c["suite"], c["scenario"], c["mutant"]): c for c in cells}
    summary = {"runtimes": runtimes, "primary_runtime": primary, "scenarios": len(scenarios), "suites": {}}
    for runtime in runtimes:
        for suite in SUITES:
            rows = [c for c in cells if c["runtime"] == runtime and c["suite"] == suite]
            controls = [c for c in rows if c["mutant"] == "control"]
            mutants = [c for c in rows if c["mutant"] != "control"]
            per = {}
            for m in MUTANTS:
                part = [c for c in mutants if c["mutant"] == m.name]
                per[m.name] = {"applicable": len(part), "killed": sum(bool(c["failed"]) for c in part),
                               "errors": sum(bool(c["error"]) for c in part)}
                per[m.name]["kill_rate"] = _rate(per[m.name]["killed"], per[m.name]["applicable"])
                # How often the suite's events can even trigger the mutated behaviour (a suite can miss a defect by not exercising it).
                per[m.name]["exercised"] = _rate(per[m.name]["applicable"], len(controls))
            summary["suites"][f"{runtime}/{suite}"] = {
                "control_pass": sum(not c["failed"] and not c["error"] for c in controls), "control_total": len(controls),
                "applicable_mutants": len(mutants), "killed": sum(bool(c["failed"]) for c in mutants),
                "kill_rate": _rate(sum(bool(c["failed"]) for c in mutants), len(mutants)),
                "errors": sum(bool(c["error"]) for c in rows), "per_mutant": per}
    # Coverage gaps on the primary runtime, per suite.
    for suite in SUITES:
        per = summary["suites"].get(f"{primary}/{suite}", {}).get("per_mutant", {})
        summary.setdefault("blind_spots", {})[suite] = [m for m, v in per.items() if v["applicable"] and not v["killed"]]
        summary.setdefault("never_exercised", {})[suite] = [m for m, v in per.items() if not v["applicable"]]
        summary.setdefault("partially_exercised", {})[suite] = {m: v["exercised"] for m, v in per.items()
                                                                if v["applicable"] and v["exercised"] < 1}
    # Paired comparison and acceptance on the primary runtime.
    accepted, any_kill, kills_by_scenario, novel_total = [], [], {}, 0
    for s in scenarios:
        control_ok = all(not index[(r, "generated", s.scenario_id, "control")]["failed"] and
                         not index[(r, "generated", s.scenario_id, "control")]["error"] for r in runtimes
                         if (r, "generated", s.scenario_id, "control") in index)
        killed, fixed_killed, v1_killed = set(), set(), set()
        for m in MUTANTS:
            for suite, bucket in (("generated", killed), (REFERENCE_SUITE, fixed_killed), ("legacy_v1", v1_killed)):
                cell = index.get((primary, suite, s.scenario_id, m.name))
                if cell and cell["failed"]:
                    bucket.add(m.name)
        novel = sorted(killed - fixed_killed)
        novel_total += len(novel)
        if control_ok and killed:
            any_kill.append(s.scenario_id)
        if control_ok and novel:
            accepted.append({"scenario": s.scenario_id, "split": s.split, "base_task": s.base_task, "kills": sorted(killed),
                             "novel_kills_vs_fixed_suite": novel, "novel_kills_vs_v1": sorted(killed - v1_killed),
                             "hostile_style": s.dims["hostile_style"]})
        if control_ok:
            kills_by_scenario[s.scenario_id] = killed
    # Acceptance requires a *novel* kill: a mutant the strongest fixed suite (legacy_v2) does not catch on the same spec.
    summary["accepted"] = {"count": len(accepted), "of": len(scenarios), "with_any_kill": len(any_kill),
                           "train": sum(a["split"] == "train" for a in accepted),
                           "holdout": sum(a["split"] == "holdout" for a in accepted),
                           "novel_kill_pairs": novel_total, "reference_suite": REFERENCE_SUITE, "items": accepted}
    # Greedy minimal subset of scenarios that reproduces every mutant type the generated suite kills at all.
    target, cover = set().union(*kills_by_scenario.values()) if kills_by_scenario else set(), []
    remaining = set(target)
    while remaining:
        best = max(kills_by_scenario, key=lambda k: len(kills_by_scenario[k] & remaining))
        cover.append(best)
        remaining -= kills_by_scenario[best]
    summary["minimal_cover"] = {"mutant_types": sorted(target), "scenarios": cover, "size": len(cover)}
    # Do generated titles actually carry a routing directive of the kind the title_routes mutant reacts to?
    sensitivity = defaultdict(lambda: {"scenarios": 0, "title_triggers": 0})
    for s in scenarios:
        key = f'{s.dims["hostile_style"]}/{s.title_source}'
        sensitivity[key]["scenarios"] += 1
        sensitivity[key]["title_triggers"] += bool(re.search(TITLE_DIRECTIVE_PATTERN, s.events[0]["title"], re.I))
    summary["title_trigger_by_style"] = dict(sorted(sensitivity.items()))
    summary["dimension_effects"] = dimension_effects(scenarios, index, primary)
    # Reference vs n8n agreement on every executed cell.
    divergences = []
    if len(runtimes) == 2:
        a, b = runtimes
        for key, cell in index.items():
            if key[0] != a:
                continue
            other = index.get((b, *key[1:]))
            if other is None:
                continue
            if cell["failed"] != other["failed"] or bool(cell["error"]) != bool(other["error"]):
                divergences.append({"suite": key[1], "scenario": key[2], "mutant": key[3],
                                    a: cell["failed"] or cell["error"], b: other["failed"] or other["error"]})
    summary["divergences"] = {"compared": sum(1 for k in index if k[0] == runtimes[0] and (runtimes[1], *k[1:]) in index)
                              if len(runtimes) == 2 else None, "count": len(divergences), "items": divergences[:50]}
    return summary


def _discriminating(effects: dict, minimum_spread: float = 0.5) -> list[str]:
    """One line per mutant: the dimension values with the highest and lowest kill rates when they differ clearly."""
    lines = []
    for mutant, dims in effects.items():
        best = None
        for dim, values in dims.items():
            rated = {v: k / n for v, (k, n) in values.items() if n}
            if len(rated) < 2:
                continue
            high, low = max(rated, key=rated.get), min(rated, key=rated.get)
            spread = rated[high] - rated[low]
            if spread >= minimum_spread and (best is None or spread > best[0]):
                best = (spread, dim, high, low, rated[high], rated[low])
        if best:
            lines.append(f"{mutant}: {best[1]}={best[2]} kills {best[4]:.0%} vs {best[1]}={best[3]} {best[5]:.0%}")
    return lines


def write_report(out: Path, summary: dict) -> None:
    rows = ""
    for name, suite in summary["suites"].items():
        rows += f"<tr><td>{html.escape(name)}</td><td>{suite['control_pass']}/{suite['control_total']}</td>" \
                f"<td>{suite['killed']}/{suite['applicable_mutants']}</td><td>{suite['kill_rate']}</td><td>{suite['errors']}</td></tr>"
    mutant_rows = ""
    for m in MUTANTS:
        cols = ""
        for name, suite in summary["suites"].items():
            v = suite["per_mutant"][m.name]
            cols += f"<td>{v['killed']}/{v['applicable']}</td>"
        mutant_rows += f"<tr><td>{html.escape(m.name)}</td><td>{html.escape(m.description)}</td>{cols}</tr>"
    heads = "".join(f"<th>{html.escape(n)}</th>" for n in summary["suites"])
    extra = {"accepted": {k: v for k, v in summary["accepted"].items() if k != "items"},
             "minimal_cover": summary["minimal_cover"], "blind_spots": summary["blind_spots"],
             "never_exercised": summary["never_exercised"], "partially_exercised": summary["partially_exercised"],
             "title_trigger_by_style": summary["title_trigger_by_style"],
             "divergences": {k: v for k, v in summary["divergences"].items() if k != "items"},
             "which_input_exposes_which_defect": _discriminating(summary["dimension_effects"])}
    (out / "report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Verifier certification</title>"
        "<style>body{font:16px system-ui;margin:3em}td,th{padding:.5em;border-bottom:1px solid #ccc;text-align:left}</style>"
        "<h1>Verifier certification by mutation testing</h1><p>Fixture evidence only; production is not authorized. "
        f"Primary runtime: {html.escape(summary['primary_runtime'])}. Scenarios: {summary['scenarios']}.</p>"
        "<h2>Suites</h2><table><tr><th>Runtime/suite</th><th>Control passes</th><th>Mutants killed</th><th>Kill rate</th><th>Errors</th></tr>"
        + rows + "</table><h2>Kills per mutant (killed/applicable)</h2><table><tr><th>Mutant</th><th>Defect</th>" + heads + "</tr>"
        + mutant_rows + "</table><h2>Acceptance, gaps and agreement</h2><pre>" +
        html.escape(json.dumps(extra, indent=2)) + "</pre>", encoding="utf-8")
