import argparse
import asyncio
import json
from pathlib import Path

from .evaluation import gate
from .config import load_environment
from .evidence import Journal, dump
from .feedback import expand_failures
from .memory import Memory
from .report import render
from .rollout import Rollout
from .runner import compare, load_outcomes
from .scenarios import generate, load_scenarios, write_scenarios
from .traffic import replay_traffic


def json_file(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Fictional service-desk agent migration lab")
    sub = root.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Create reproducible synthetic populations and tasks")
    gen.add_argument("--population", type=Path, default=Path("configs/population.json"))
    gen.add_argument("--count", type=int, default=100)
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--suite", choices=["representative", "stress"], default="representative")
    gen.add_argument("--split", choices=["development", "holdout"], default="development")
    gen.add_argument("--out", type=Path, required=True)
    run = sub.add_parser("compare", help="Run paired old/new systems in isolated worlds")
    run.add_argument("--scenarios", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    for variant in ("baseline", "candidate"):
        run.add_argument(f"--{variant}-backend", choices=["rules", "openai-compatible", "nooa"], default="rules")
    run.add_argument("--migration-mode", choices=["cold", "migrated"], default="migrated")
    run.add_argument("--max-steps", type=int, default=12)
    run.add_argument("--episode-timeout", type=float, default=600)
    traffic = sub.add_parser("traffic", help="Route and execute simulated user flows through the local controller")
    traffic.add_argument("--scenarios", type=Path, required=True)
    traffic.add_argument("--out", type=Path, required=True)
    traffic.add_argument("--db", type=Path, required=True)
    traffic.add_argument("--candidate-backend", choices=["rules", "openai-compatible", "nooa"], default="rules")
    monitor = sub.add_parser("monitor", help="Assess collected canary evidence and optionally latch local rollback")
    monitor.add_argument("--run", type=Path, required=True)
    monitor.add_argument("--db", type=Path, required=True)
    monitor.add_argument("--min-candidate-episodes", type=int, default=20)
    monitor.add_argument("--min-success-rate", type=float, default=0.9)
    monitor.add_argument("--apply-rollback", action="store_true")
    check = sub.add_parser("gate", help="Evaluate fixed-look paired release evidence")
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--config", default="configs/gates.json")
    report = sub.add_parser("report", help="Write a portable HTML evidence report")
    report.add_argument("--run", type=Path, required=True)
    failures = sub.add_parser("expand-failures", help="Create development stress tasks from candidate failures")
    failures.add_argument("--scenarios", type=Path, required=True)
    failures.add_argument("--run", type=Path, required=True)
    failures.add_argument("--out", type=Path, required=True)
    feedback = sub.add_parser("rate", help="Attach a manual review to an existing episode")
    feedback.add_argument("--run", type=Path, required=True)
    feedback.add_argument("--scenario", required=True)
    feedback.add_argument("--variant", choices=["baseline", "candidate"], required=True)
    feedback.add_argument("--rating", type=int, choices=range(1, 6), required=True)
    feedback.add_argument("--comment", default="")
    migration = sub.add_parser("migrate-memory", help="Convert a local memory snapshot between v1/v2")
    migration.add_argument("--snapshot", type=Path, required=True)
    migration.add_argument("--to", type=int, choices=[1, 2], required=True)
    migration.add_argument("--out", type=Path, required=True)
    rollout = sub.add_parser("rollout", help="Exercise the local canary controller")
    rollout.add_argument("--db", type=Path, required=True)
    operations = rollout.add_subparsers(dest="operation", required=True)
    init = operations.add_parser("init")
    init.add_argument("--experiment", required=True)
    init.add_argument("--salt", required=True)
    ramp = operations.add_parser("set-percent")
    ramp.add_argument("--percent", type=float, required=True)
    ramp.add_argument("--gate", required=True)
    route = operations.add_parser("route")
    route.add_argument("--tenant", required=True)
    route.add_argument("--session", required=True)
    rollback = operations.add_parser("rollback")
    rollback.add_argument("--reason", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    load_environment()
    if args.command == "generate":
        rows = generate(args.population, args.count, args.seed, args.suite, args.split)
        write_scenarios(args.out, rows)
        print(f"Wrote {len(rows)} synthetic scenarios to {args.out}")
    elif args.command == "compare":
        if args.max_steps < 1 or args.episode_timeout <= 0:
            raise ValueError("Step budget and timeout must be positive")
        rows = load_scenarios(args.scenarios)
        asyncio.run(compare(rows, args.out, args.baseline_backend, args.candidate_backend,
                            args.migration_mode, args.max_steps, args.episode_timeout))
        print(f"Evidence written to {args.out}")
    elif args.command == "gate":
        result = gate(load_outcomes(args.run / "outcomes.jsonl"), json_file(args.config))
        dump(args.run / "gate.json", result)
        print(json.dumps(result, indent=2))
        if result["decision"] == "hold":
            raise SystemExit(2)
    elif args.command == "traffic":
        asyncio.run(replay_traffic(load_scenarios(args.scenarios), args.out, args.db, args.candidate_backend))
    elif args.command == "monitor":
        if args.min_candidate_episodes < 1 or not 0 <= args.min_success_rate <= 1:
            raise ValueError("Invalid monitoring thresholds")
        candidates = [r for r in load_outcomes(args.run / "outcomes.jsonl") if r.variant == "candidate"]
        reasons = []
        if any(r.safety_failure for r in candidates):
            reasons.append("candidate unauthorized tool attempt")
        if any(r.status == "error" for r in candidates):
            reasons.append("candidate execution error")
        rate = sum(r.success for r in candidates) / len(candidates) if candidates else None
        if len(candidates) >= args.min_candidate_episodes and rate < args.min_success_rate:
            reasons.append("candidate success below configured monitoring floor")
        result = {"candidate_episodes": len(candidates), "success_rate": rate,
                  "reasons": reasons, "rollback_applied": False,
                  "note": "Operational stop rules, not a statistical promotion test."}
        if reasons and args.apply_rollback:
            controller = Rollout(args.db)
            try:
                controller.rollback("; ".join(reasons))
                result["rollback_applied"] = True
            finally:
                controller.close()
        dump(args.run / "monitor.json", result)
        print(json.dumps(result, indent=2))
    elif args.command == "report":
        gate_path = args.run / "gate.json"
        render(load_outcomes(args.run / "outcomes.jsonl"), args.run / "report.html",
               json_file(str(gate_path)) if gate_path.exists() else None)
        print(args.run / "report.html")
    elif args.command == "expand-failures":
        count = expand_failures(load_scenarios(args.scenarios), load_outcomes(args.run / "outcomes.jsonl"), args.out)
        print(f"Wrote {count} new development stress scenarios")
    elif args.command == "rate":
        outcomes = load_outcomes(args.run / "outcomes.jsonl")
        match = next((r for r in outcomes if r.scenario_id == args.scenario and r.variant == args.variant), None)
        if match is None:
            raise ValueError("Unknown scenario/variant")
        Journal(args.run / "human-reviews.jsonl", run_id=match.run_id,
                scenario_id=match.scenario_id, variant=match.variant).emit(
                    "human.review", rating=args.rating, comment=args.comment,
                    reviewer="manual-local", source="human", rating_schema="1_to_5")
    elif args.command == "migrate-memory":
        snapshot = json_file(str(args.snapshot))
        scope = snapshot["scope"]
        journal = Journal(args.out.with_suffix(".events.jsonl"), operation="manual-memory-migration")
        memory = Memory(snapshot["schema_version"], scope["tenant"], scope["user"], scope["namespace"], journal)
        memory.data = snapshot["data"]
        dump(args.out, memory.migrate(args.to).snapshot())
    elif args.command == "rollout":
        controller = Rollout(args.db)
        try:
            if args.operation == "init":
                result = controller.initialize(args.experiment, args.salt)
            elif args.operation == "set-percent":
                result = controller.set_percent(args.percent, json_file(args.gate))
            elif args.operation == "route":
                result = controller.route(args.tenant, args.session)
            else:
                result = controller.rollback(args.reason)
            print(json.dumps(result, indent=2))
        finally:
            controller.close()


if __name__ == "__main__":
    main()
