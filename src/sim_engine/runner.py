import asyncio
import json
import os
import platform
import time
import uuid
from pathlib import Path

from . import __version__
from .agents import NooaBackend, OpenAICompatible, run_llm, run_rules
from .contracts import Outcome, Scenario
from .config import llm_settings, load_environment
from .evaluation import summarize, verify
from .evidence import Journal, digest, dump
from .memory import Memory
from .world import World


async def episode(scenario: Scenario, variant: str, backend_name: str, root: Path,
                  run_id: str, migration_mode: str, max_steps: int,
                  episode_timeout: float) -> Outcome:
    folder = root / "episodes" / scenario.scenario_id / variant
    journal = Journal(folder / "events.jsonl", run_id=run_id,
                      scenario_id=scenario.scenario_id, variant=variant,
                      tenant_id=scenario.persona.tenant_id, user_id=scenario.persona.user_id)
    schema = 1 if variant == "baseline" or migration_mode == "migrated" else 2
    memory = Memory(schema, scenario.persona.tenant_id, scenario.persona.user_id,
                    f"{run_id}/{scenario.scenario_id}/{variant}", journal)
    if scenario.stale_memory:
        memory.write("workspace_role", "admin", source="expired_legacy_cache")
    world = World(scenario, memory, journal)
    backend = None
    status, error = "completed", None
    started = time.perf_counter()

    async def interact() -> None:
        nonlocal backend
        if backend_name == "openai-compatible":
            backend = OpenAICompatible(journal, variant)
        elif backend_name == "nooa":
            backend = NooaBackend(journal, folder, variant)
        for session in (1, 2):
            message = world.start_session(session)
            if session == 2 and variant == "candidate" and migration_mode == "migrated":
                dump(folder / "pre-migration-memory.json", world.memory.snapshot())
                world.memory = world.memory.migrate(2)
                dump(folder / "post-migration-memory.json", world.memory.snapshot())
            # For migrated runs, session 1 is always the legacy harness and schema.
            if session == 1 and variant == "candidate" and migration_mode == "migrated":
                await run_rules(world, message, "baseline")
            elif backend_name == "rules":
                await run_rules(world, message, variant)
            else:
                await run_llm(world, message, backend, max_steps)
            journal.emit("state.checkpoint", snapshot=world.snapshot())

    try:
        await asyncio.wait_for(interact(), timeout=episode_timeout)
    except Exception as exc:
        status = "error"
        # Do not serialize credentials, HTTP headers, or provider error bodies.
        error = type(exc).__name__
        journal.emit("episode.error", error_type=error)
    finally:
        if backend is not None:
            try:
                await backend.close()
            except Exception as exc:
                journal.emit("backend.close_error", error_type=type(exc).__name__)
    elapsed = (time.perf_counter() - started) * 1000
    checks = verify(scenario, world)
    passed = status == "completed" and all(c.passed for c in checks)
    safety = bool(world.denied_attempts)
    cost = 0.0 if backend_name == "rules" else None
    input_tokens = getattr(backend, "input_tokens", 0)
    output_tokens = getattr(backend, "output_tokens", 0)
    if backend_name == "nooa" or (backend_name == "openai-compatible" and
                                   not getattr(backend, "usage_available", False)):
        input_tokens = output_tokens = None
    if backend_name == "openai-compatible":
        price_in, price_out = os.getenv("SIM_INPUT_USD_PER_MILLION"), os.getenv("SIM_OUTPUT_USD_PER_MILLION")
        if price_in and price_out and input_tokens is not None and output_tokens is not None:
            cost = (input_tokens * float(price_in) + output_tokens * float(price_out)) / 1_000_000
    outcome = Outcome(
        run_id=run_id, scenario_id=scenario.scenario_id, variant=variant, backend=backend_name,
        cohort=scenario.cohort, split=scenario.split, suite=scenario.suite, status=status,
        checks=checks, success=passed, safety_failure=safety,
        user_rating_proxy=5 if passed else (1 if safety else 2),
        latency_ms=elapsed, input_tokens=input_tokens, output_tokens=output_tokens,
        estimated_cost_usd=cost, error=error, migration_mode=migration_mode,
    )
    dump(folder / "final-state.json", world.snapshot())
    dump(folder / "outcome.json", outcome.model_dump())
    journal.emit("episode.completed", outcome=outcome.model_dump())
    return outcome


async def compare(scenarios: list[Scenario], output: Path, baseline_backend: str,
                  candidate_backend: str, migration_mode: str, max_steps: int,
                  episode_timeout: float) -> list[Outcome]:
    load_environment()
    inference = {variant: llm_settings(variant).public_metadata()
                 for variant, name in (("baseline", baseline_backend), ("candidate", candidate_backend))
                 if name == "openai-compatible"}
    # New output per run avoids mixing retries with independent observations.
    output.mkdir(parents=True, exist_ok=False)
    run_id = str(uuid.uuid4())
    dump(output / "manifest.json", {
        "run_id": run_id, "application_version": __version__, "python": platform.python_version(),
        "baseline_backend": baseline_backend, "candidate_backend": candidate_backend,
        "migration_mode": migration_mode, "max_steps": max_steps,
        "episode_timeout_seconds": episode_timeout,
        "dataset_sha256": digest([s.model_dump() for s in scenarios]),
        "scenario_count": len(scenarios), "origin": "synthetic",
        "model": os.getenv("SIM_LLM_MODEL"), "nooa_alias": os.getenv("SIM_NOOA_MODEL"),
        "variant_models": {v: os.getenv(f"SIM_{v.upper()}_LLM_MODEL") for v in ("baseline", "candidate")},
        "variant_nooa_aliases": {v: os.getenv(f"SIM_{v.upper()}_NOOA_MODEL") for v in ("baseline", "candidate")},
        "inference": inference,
        "usage_note": "NOOA usage remains in its native journal and is not aggregated here.",
    })
    outcomes = []
    for i, scenario in enumerate(scenarios):
        # Alternate order without allowing shared agent or environment state.
        variants = ("baseline", "candidate") if i % 2 == 0 else ("candidate", "baseline")
        for variant in variants:
            name = baseline_backend if variant == "baseline" else candidate_backend
            row = await episode(scenario, variant, name, output, run_id,
                                migration_mode, max_steps, episode_timeout)
            outcomes.append(row)
            with (output / "outcomes.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(row.model_dump_json() + "\n")
        print(f"[{i + 1}/{len(scenarios)}] {scenario.scenario_id}", flush=True)
    dump(output / "summary.json", summarize(outcomes))
    return outcomes


def load_outcomes(path: Path) -> list[Outcome]:
    return [Outcome.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
