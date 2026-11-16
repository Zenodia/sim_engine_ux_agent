from pathlib import Path

from .contracts import Outcome, Scenario
from .evidence import digest, dump
from .scenarios import FLAGS, write_scenarios


def expand_failures(scenarios: list[Scenario], outcomes: list[Outcome], destination: Path) -> int:
    """Failure-guided one-factor mutations; sealed holdout rows are never recycled."""
    sources = {s.scenario_id: s for s in scenarios}
    if {o.scenario_id for o in outcomes} - set(sources):
        raise ValueError("Outcome scenarios do not match the supplied dataset")
    failed = {o.scenario_id for o in outcomes if o.variant == "candidate" and not o.success}
    rows, seen = [], set()
    skipped_holdout = 0
    for sid in sorted(failed):
        source = sources[sid]
        if source.split == "holdout":
            skipped_holdout += 1
            continue
        for flag in FLAGS:
            row = source.model_copy(deep=True)
            setattr(row, flag, not getattr(row, flag))
            row.scenario_id = f"{source.scenario_id}-mutation-{flag}"
            row.suite = "stress"
            # Old paraphrases may contradict the mutated task; regenerate them separately.
            row.session_messages = {}
            row.lineage = {"origin": "synthetic", "generator": "failure-mutation-v1",
                           "parent_scenario": sid, "changed_factor": flag,
                           "parent_digest": digest(source.model_dump())}
            identity = digest(row.model_dump(exclude={"scenario_id", "lineage"}))
            if identity not in seen:
                rows.append(row)
                seen.add(identity)
    write_scenarios(destination, rows)
    dump(destination.with_suffix(".feedback.json"), {"new_rows": len(rows),
         "failed_candidate_scenarios": len(failed), "skipped_holdout": skipped_holdout,
         "note": "No holdout tasks are used to create optimization data."})
    return len(rows)
