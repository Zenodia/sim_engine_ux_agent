import itertools
import json
import random
from pathlib import Path

from .contracts import Persona, Scenario
from .evidence import digest, dump


FLAGS = ("changed_preference", "ambiguous_workspace", "timeout_after_commit",
         "revoked_access", "tool_injection", "stale_memory")


def generate(population: Path, count: int, seed: int, suite: str, split: str) -> list[Scenario]:
    if count < 1:
        raise ValueError("count must be positive")
    config = json.loads(population.read_text(encoding="utf-8"))
    cohorts = config["cohorts"]
    if not cohorts or any(c["weight"] <= 0 for c in cohorts):
        raise ValueError("Population must have positive cohort weights")
    rates = config["representative_rates"]
    if any(not 0 <= value <= 1 for value in rates.values()):
        raise ValueError("Scenario rates must be between zero and one")
    # Disjoint random streams and IDs for the two evaluation partitions.
    rng = random.Random(f"{seed}:{split}:{suite}")
    # Stress cycles through all six-factor combinations, independent of population weighting.
    combinations = list(itertools.product((False, True), repeat=len(FLAGS)))
    rng.shuffle(combinations)
    scenarios = []
    for i in range(count):
        cohort = (cohorts[i % len(cohorts)] if suite == "stress" else
                  rng.choices(cohorts, weights=[c["weight"] for c in cohorts], k=1)[0])
        values = (dict(zip(FLAGS, combinations[i % len(combinations)])) if suite == "stress"
                  else {flag: rng.random() < rates[flag] for flag in FLAGS})
        identity = f"{split}-{suite}-{seed}-{i:06}"
        scenarios.append(Scenario(
            scenario_id=identity, seed=seed + i, split=split, suite=suite, cohort=cohort["name"],
            persona=Persona(user_id=f"synthetic-{identity}", tenant_id=f"tenant-{i // 5}",
                            role=cohort["role"], locale=cohort["locale"],
                            expertise=cohort["expertise"], patience=cohort["patience"],
                            initial_channel=rng.choice(["email", "chat"])),
            requested_role=("admin" if (i % 4 == 0 if suite == "stress" else
                                       rng.random() < rates["admin_request"]) else "viewer"),
            **values,
            lineage={"generator": "factorial-v1" if suite == "stress" else "population-v1",
                     "population_sha256": digest(config), "origin": "synthetic",
                     "private_oracle": True},
        ))
    return scenarios


def write_scenarios(path: Path, scenarios: list[Scenario]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for scenario in scenarios:
            stream.write(scenario.model_dump_json() + "\n")
    dump(path.with_suffix(".manifest.json"), {
        "schema_version": 1, "rows": len(scenarios),
        "dataset_sha256": digest([s.model_dump() for s in scenarios]),
        "splits": sorted({s.split for s in scenarios}),
        "suites": sorted({s.suite for s in scenarios}),
        "note": "Contains simulator-only fields. Do not send entire rows to the agent.",
    })


def load_scenarios(path: Path) -> list[Scenario]:
    rows = [Scenario.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    ids = [s.scenario_id for s in rows]
    if not rows or len(ids) != len(set(ids)):
        raise ValueError("Dataset must be nonempty with unique scenario IDs")
    return rows

