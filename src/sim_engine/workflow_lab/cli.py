import argparse
import json
from pathlib import Path

from sim_engine.config import load_environment
from sim_engine.evidence import dump

from .compiler import compile_workflow
from .contracts import Spec
from .evaluate import evaluate
from .fixtures import serve as serve_fixtures
from .gateway import DraftRequest, Gateway, serve as serve_gateway
from .migration import Migration, load_evidence
from .runtime import N8nRuntime, ReferenceRuntime
from .tasks import generate, load, write


def make_runtime(name, root, activate=False):
    return ReferenceRuntime(root.parent / (root.name + "-fixtures.sqlite")) if name == "reference" else N8nRuntime(activate)


def parser():
    root = argparse.ArgumentParser(description="Enterprise n8n workflow creator and fixture migration lab")
    sub = root.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--count", type=int, default=100)
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--out", type=Path, required=True)
    sdg = sub.add_parser("paraphrase")
    sdg.add_argument("--tasks", type=Path, required=True)
    sdg.add_argument("--out", type=Path, required=True)
    sdg.add_argument("--batch-size", type=int, default=5)
    sdg.add_argument("--max-requests", type=int, default=20)
    sdg.add_argument("--max-tokens", type=int, default=2048)
    sdg.add_argument("--resume", action="store_true")
    run = sub.add_parser("evaluate")
    run.add_argument("--tasks", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--executor", choices=["reference", "n8n"], default="reference")
    run.add_argument("--creator", choices=["rules", "llm"], default="rules")
    run.add_argument("--stage", choices=["offline", "shadow", "canary"], default="offline")
    run.add_argument("--controller", type=Path)
    run.add_argument("--allow-activation", action="store_true")
    fixtures = sub.add_parser("fixtures")
    fixtures.add_argument("--db", type=Path, default=Path("artifacts/n8n-fixtures.sqlite"))
    fixtures.add_argument("--host", default="127.0.0.1")
    fixtures.add_argument("--port", type=int, default=8091)
    control = sub.add_parser("control")
    control.add_argument("--db", type=Path, required=True)
    ops = control.add_subparsers(dest="operation", required=True)
    init = ops.add_parser("init")
    init.add_argument("--from-run", type=Path, required=True)
    init.add_argument("--salt", default="incident-creator-v1")
    init.add_argument("--max-latency-ms", type=float, default=60000)
    init.add_argument("--max-cost-usd", type=float)
    advance = ops.add_parser("advance")
    advance.add_argument("--phase", choices=["offline", "shadow", "canary", "expansion", "full"], required=True)
    advance.add_argument("--evidence", type=Path, required=True)
    advance.add_argument("--percent", type=float)
    observe = ops.add_parser("observe")
    observe.add_argument("--evidence", type=Path, required=True)
    route = ops.add_parser("route")
    route.add_argument("--tenant", required=True)
    route.add_argument("--session", required=True)
    rollback = ops.add_parser("rollback")
    rollback.add_argument("--reason", required=True)
    ops.add_parser("status")
    for command in ("serve", "draft"):
        gateway = sub.add_parser(command)
        gateway.add_argument("--controller", type=Path, required=True)
        gateway.add_argument("--out", type=Path, required=True)
        gateway.add_argument("--executor", choices=["reference", "n8n"], default="reference")
        gateway.add_argument("--creator", choices=["rules", "llm"], default="rules")
        gateway.add_argument("--import-drafts", action="store_true")
        if command == "serve":
            gateway.add_argument("--host", default="127.0.0.1")
            gateway.add_argument("--port", type=int, default=8088)
        else:
            gateway.add_argument("--request", type=Path, required=True)
    export = sub.add_parser("export")
    export.add_argument("--spec", type=Path, required=True)
    export.add_argument("--tenant", default="example-tenant")
    export.add_argument("--namespace", default="example-incident-workflow")
    export.add_argument("--fixture-url", default="http://fixtures:8091")
    export.add_argument("--out", type=Path, required=True)
    scn = sub.add_parser("scenarios-dd", help="Generate hidden test scenarios with NeMo Data Designer")
    scn.add_argument("--count", type=int, default=24)
    scn.add_argument("--no-llm", action="store_true", help="Use deterministic template titles instead of the LLM")
    scn.add_argument("--out", type=Path, required=True)
    cert = sub.add_parser("certify", help="Mutation-test the verifier on the reference and/or real n8n")
    cert.add_argument("--scenarios", type=Path, required=True)
    cert.add_argument("--executor", choices=["reference", "n8n", "both"], default="both")
    cert.add_argument("--allow-activation", action="store_true")
    cert.add_argument("--limit", type=int)
    cert.add_argument("--out", type=Path, required=True)
    deploy = sub.add_parser("import-draft")
    deploy.add_argument("--workflow", type=Path, required=True)
    deploy.add_argument("--record-out", type=Path, required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--count", type=int, default=100)
    demo.add_argument("--out", type=Path, required=True)
    demo.add_argument("--canary-percent", type=float, default=20)
    demo.add_argument("--expansion-percent", type=float, default=50)
    return root


def demo(args):
    if not 0 < args.canary_percent < args.expansion_percent < 100:
        raise ValueError("Exposure steps must satisfy 0 < canary < expansion < 100")
    args.out.mkdir(parents=True, exist_ok=False)
    tasks = generate(args.count)
    write(args.out / "tasks.jsonl", tasks)
    runtime = ReferenceRuntime(args.out / "fixtures.sqlite")
    initial = evaluate(tasks, args.out / "offline", runtime)
    controller = Migration(args.out / "migration.sqlite")
    try:
        controller.initialize(initial.release, "reference")
        controller.advance("offline", load_evidence(args.out / "offline/baseline-evidence.json"))
        controller.advance("shadow", load_evidence(args.out / "offline/evidence.json"))
        evaluate(tasks, args.out / "shadow", runtime, stage="shadow", controller=controller)
        controller.advance("canary", load_evidence(args.out / "shadow/evidence.json"), args.canary_percent)
        evaluate(tasks, args.out / "canary", runtime, stage="canary", controller=controller)
        report = load_evidence(args.out / "canary/evidence.json")
        controller.observe(report)
        controller.advance("expansion", report, args.expansion_percent)
        evaluate(tasks, args.out / "expansion", runtime, stage="canary", controller=controller)
        report = load_evidence(args.out / "expansion/evidence.json")
        controller.observe(report)
        controller.advance("full", report)
        evaluate(tasks, args.out / "full", runtime, stage="canary", controller=controller)
        controller.observe(load_evidence(args.out / "full/evidence.json"))
        if controller.status()["phase"] != "full":
            raise RuntimeError("Full-exposure candidate verification triggered rollback")
        dump(args.out / "full-migration.json", controller.status())
        controller.rollback("Reference demo recovery drill after reaching full fixture exposure")
        dump(args.out / "rollback.json", controller.status())
        assert controller.route("new-tenant", "after-rollback")["arm"] == "baseline"
        print("Reference migration demo completed. Actual n8n execution is a separate test.")
    finally:
        controller.close()


def main():
    args = parser().parse_args()
    load_environment()
    if args.command == "generate":
        write(args.out, generate(args.count, args.seed))
    elif args.command == "paraphrase":
        from .sdg import paraphrase
        paraphrase(load(args.tasks), args.out, args.batch_size, args.max_requests, args.max_tokens, args.resume)
    elif args.command == "evaluate":
        if args.stage == "shadow" and args.controller is None:
            raise ValueError("Shadow requires a controller with passing offline evidence")
        runtime = make_runtime(args.executor, args.out, args.allow_activation)
        control = Migration(args.controller) if args.controller else None
        try:
            evidence = evaluate(load(args.tasks), args.out, runtime, args.creator, args.stage, control)
            print(evidence.model_dump_json(indent=2))
        finally:
            if control:
                control.close()
    elif args.command == "scenarios-dd":
        from .scenarios_dd import generate_scenarios, write_scenarios
        scenarios, stats = generate_scenarios(args.count, use_llm=not args.no_llm)
        write_scenarios(args.out, scenarios, stats)
        print(json.dumps(stats, indent=2))
    elif args.command == "certify":
        from .certify import certify
        from .scenarios_dd import load_scenarios
        scenarios = load_scenarios(args.scenarios)[:args.limit]
        runtimes = []
        if args.executor in ("reference", "both"):
            runtimes.append(make_runtime("reference", args.out))
        if args.executor in ("n8n", "both"):
            runtimes.append(make_runtime("n8n", args.out, args.allow_activation))
        summary = certify(scenarios, runtimes, args.out)
        print(json.dumps({k: v for k, v in summary.items() if k not in ("accepted", "divergences")}, indent=2))
        print(json.dumps({"accepted": {k: v for k, v in summary["accepted"].items() if k != "items"},
                          "minimal_cover": summary["minimal_cover"], "title_trigger_by_style": summary["title_trigger_by_style"],
                          "divergences": {k: v for k, v in summary["divergences"].items() if k != "items"}}, indent=2))
    elif args.command == "fixtures":
        serve_fixtures(args.db, args.host, args.port)
    elif args.command == "control":
        control = Migration(args.db)
        try:
            if args.operation == "init":
                evidence = load_evidence(args.from_run / "evidence.json")
                result = control.initialize(evidence.release, evidence.executor, args.salt,
                                            max_latency_ms=args.max_latency_ms, max_cost_usd=args.max_cost_usd)
            elif args.operation == "advance":
                result = control.advance(args.phase, load_evidence(args.evidence), args.percent)
            elif args.operation == "observe":
                result = control.observe(load_evidence(args.evidence))
            elif args.operation == "route":
                result = control.route(args.tenant, args.session)
            elif args.operation == "rollback":
                result = control.rollback(args.reason)
            else:
                result = control.status()
            print(json.dumps(result, indent=2))
        finally:
            control.close()
    elif args.command in ("serve", "draft"):
        runtime = make_runtime(args.executor, args.out)
        gateway = Gateway(args.controller, args.out, runtime, args.creator, args.import_drafts)
        if args.command == "serve":
            serve_gateway(gateway, args.host, args.port)
        else:
            print(json.dumps(gateway.submit(DraftRequest.model_validate_json(args.request.read_text(encoding="utf-8"))), indent=2))
    elif args.command == "export":
        spec = Spec.model_validate_json(args.spec.read_text(encoding="utf-8"))
        from .creator import enforce_policy
        enforce_policy(spec)
        dump(args.out, compile_workflow(spec, args.namespace, args.tenant, args.fixture_url))
    elif args.command == "import-draft":
        workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
        if not workflow.get("name", "").startswith("sim-engine:"):
            raise ValueError("Only lab-owned exports may be imported through this command")
        dump(args.record_out, N8nRuntime().import_draft(workflow))
    elif args.command == "demo":
        demo(args)


if __name__ == "__main__":
    main()
