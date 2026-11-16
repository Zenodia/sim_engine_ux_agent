import uuid
from pathlib import Path

from .contracts import Scenario
from .evaluation import summarize
from .evidence import dump
from .rollout import Rollout
from .runner import episode


async def replay_traffic(scenarios: list[Scenario], root: Path, db: Path, candidate_backend: str) -> None:
    """Route fictional complete user flows. This is a local canary exercise."""
    root.mkdir(parents=True, exist_ok=False)
    controller = Rollout(db)
    run_id = str(uuid.uuid4())
    results, assignments = [], []
    try:
        for scenario in scenarios:
            assignment = controller.route(scenario.persona.tenant_id, scenario.scenario_id)
            assignments.append(assignment)
            if assignment["arm"] == "drain":
                continue
            variant = assignment["arm"]
            backend = candidate_backend if variant == "candidate" else "rules"
            result = await episode(scenario, variant, backend, root, run_id, "migrated", 12, 600)
            results.append(result)
            with (root / "outcomes.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(result.model_dump_json() + "\n")
    finally:
        controller.close()
    dump(root / "assignments.json", assignments)
    dump(root / "summary.json", summarize(results))
    dump(root / "manifest.json", {"run_id": run_id, "origin": "synthetic", "mode": "local-canary-replay",
                                  "note": "These are unpaired assigned flows; do not use the paired gate command."})
